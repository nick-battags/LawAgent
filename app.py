from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import secrets as _secrets

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from langchain_text_splitters import RecursiveCharacterTextSplitter

from scripts.ma_corpus_db import get_db, extract_text, classify_document, normalize_ws
from scripts.ma_crag_engine import (
    SAMPLE_CONTRACT,
    TEMPLATE_QUESTIONS,
    analyze_contract,
    generate_agreement,
    retrieve,
)
from scripts.ma_db_crag_engine import analyze_contract_v2, generate_agreement_v2, ingest_deposited_documents
from scripts.crag_pipeline import pipeline_status
from scripts.crag_pipeline import runtime_control_status, set_forced_runtime_mode
from scripts.edgar_fetcher import search_edgar_filings, search_and_ingest
from scripts.dataset_fetcher import ingest_maud, ingest_cuad, dataset_summary, get_ingest_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or _secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
if os.environ.get("NODE_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True
ADMIN_PIN = os.environ.get("ADMIN_PIN", "")
UPLOAD_DIR = Path("training_docs_inbox/uploads")
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

_session_store: dict[str, list[dict[str, Any]]] = {}
_session_lock = threading.Lock()
MAX_SESSIONS = 50
MAX_SESSION_DOCS = 10
DEFAULT_EDGAR_END_DATE = date.today().isoformat()
_vector_sync_lock = threading.RLock()
_vector_sync_state: dict[str, Any] = {
    "running": False,
    "last_reason": "",
    "last_trigger": "",
    "last_started": "",
    "last_finished": "",
    "last_scope": "",
    "last_document_ids": [],
    "last_result": None,
    "last_error": "",
    "pending_full": False,
    "pending_document_ids": [],
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vector_sync_snapshot() -> dict[str, Any]:
    with _vector_sync_lock:
        snap = dict(_vector_sync_state)
    return snap


def _start_vector_sync(
    reason: str,
    document_ids: list[int] | None = None,
    trigger: str = "auto",
) -> dict[str, Any]:
    normalized_ids = sorted(set(document_ids or []))
    with _vector_sync_lock:
        if _vector_sync_state["running"]:
            if normalized_ids:
                pending = set(_vector_sync_state.get("pending_document_ids") or [])
                pending.update(normalized_ids)
                _vector_sync_state["pending_document_ids"] = sorted(pending)
            else:
                _vector_sync_state["pending_full"] = True
            return {"status": "running", **_vector_sync_snapshot()}

        _vector_sync_state["running"] = True
        _vector_sync_state["last_reason"] = reason
        _vector_sync_state["last_trigger"] = trigger
        _vector_sync_state["last_started"] = _utc_now_iso()
        _vector_sync_state["last_finished"] = ""
        _vector_sync_state["last_scope"] = "documents" if normalized_ids else "full"
        _vector_sync_state["last_document_ids"] = normalized_ids
        _vector_sync_state["last_error"] = ""
        _vector_sync_state["last_result"] = None

    def run_sync() -> None:
        try:
            from scripts.vector_store import get_vector_store

            store = get_vector_store()
            if normalized_ids:
                result = store.sync_documents(normalized_ids)
            else:
                result = store.sync_from_postgres()
            logger.info("Vector sync complete (%s/%s): %s", trigger, reason, result)
            with _vector_sync_lock:
                _vector_sync_state["last_result"] = result
                _vector_sync_state["last_error"] = ""
        except Exception:
            err = traceback.format_exc()
            logger.warning("Vector sync failed (%s/%s): %s", trigger, reason, err)
            with _vector_sync_lock:
                _vector_sync_state["last_error"] = err
        finally:
            next_ids: list[int] | None = None
            should_run_follow_up = False
            with _vector_sync_lock:
                _vector_sync_state["running"] = False
                _vector_sync_state["last_finished"] = _utc_now_iso()
                pending_full = bool(_vector_sync_state.get("pending_full"))
                pending_ids = sorted(set(_vector_sync_state.get("pending_document_ids") or []))
                _vector_sync_state["pending_full"] = False
                _vector_sync_state["pending_document_ids"] = []
                if pending_full:
                    should_run_follow_up = True
                    next_ids = None
                elif pending_ids:
                    should_run_follow_up = True
                    next_ids = pending_ids
            if should_run_follow_up:
                _start_vector_sync("queued follow-up sync", document_ids=next_ids, trigger="queued")

    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()
    return {"status": "started", **_vector_sync_snapshot()}


def _trigger_vector_sync(reason: str, document_ids: list[int] | None = None) -> None:
    state = _start_vector_sync(reason, document_ids=document_ids, trigger="auto")
    if state.get("status") == "running":
        logger.info(
            "Vector sync already running; queued request (%s, doc_ids=%s)",
            reason,
            document_ids or [],
        )


def _extract_document_ids(items: list[dict[str, Any]]) -> list[int]:
    doc_ids: list[int] = []
    for item in items:
        raw = item.get("document_id")
        try:
            if raw is not None:
                doc_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted(set(doc_ids))


def _get_session_docs(session_id: str) -> list[dict[str, Any]]:
    with _session_lock:
        return list(_session_store.get(session_id, []))


def _add_session_doc(session_id: str, doc: dict[str, Any]) -> bool:
    with _session_lock:
        if session_id not in _session_store:
            if len(_session_store) >= MAX_SESSIONS:
                oldest = next(iter(_session_store))
                del _session_store[oldest]
            _session_store[session_id] = []
        if len(_session_store[session_id]) >= MAX_SESSION_DOCS:
            return False
        _session_store[session_id].append(doc)
        return True


@app.errorhandler(Exception)
def handle_exception(exc):
    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description}), exc.code
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.path, traceback.format_exc())
    return jsonify({"error": "Internal server error. Check logs for details."}), 500


@app.after_request
def add_dev_headers(response):
    if os.environ.get("NODE_ENV") != "production":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return redirect("/hub")


def _admin_authed() -> bool:
    if not ADMIN_PIN:
        logger.warning("ADMIN_PIN not set - admin access disabled for safety. Set ADMIN_PIN to enable admin features.")
        return False
    return session.get("admin_authed") is True


def _require_admin(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _admin_authed():
            return jsonify({"error": "Admin authentication required."}), 401
        return f(*args, **kwargs)
    return wrapper


@app.get("/admin")
def admin():
    if not _admin_authed():
        return redirect(url_for("admin_login"))
    return render_template("admin.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PIN:
        return redirect(url_for("admin"))
    error = ""
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if _secrets.compare_digest(pin, ADMIN_PIN):
            session["admin_authed"] = True
            return redirect(url_for("admin"))
        error = "Incorrect PIN. Try again."
    return render_template("admin_login.html", error=error)


@app.get("/admin/logout")
def admin_logout():
    session.pop("admin_authed", None)
    return redirect(url_for("admin_login"))


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "LawAgent Corrective RAG"})


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


@app.get("/api/sample-contract")
def sample_contract():
    return jsonify({"contract": SAMPLE_CONTRACT})


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    contract = str(payload.get("contract", ""))
    try:
        return jsonify(analyze_contract(contract))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/template/questions")
def template_questions():
    return jsonify({"questions": TEMPLATE_QUESTIONS})


@app.post("/api/template/generate")
def template_generate():
    payload = request.get_json(silent=True) or {}
    details = payload.get("details") or {}
    if not isinstance(details, dict):
        return jsonify({"error": "Template details must be an object."}), 400
    return jsonify(generate_agreement({str(k): str(v) for k, v in details.items()}))


@app.get("/api/retrieve")
def retrieve_api():
    query = request.args.get("q", "")
    return jsonify({"results": retrieve(query, top_k=6)})


@app.get("/api/v2/corpus/status")
@_require_admin
def v2_corpus_status():
    try:
        return jsonify(get_db().stats())
    except Exception as exc:
        logger.warning("Corpus status failed: %s", exc)
        return jsonify({"backend": "unavailable", "document_count": 0, "chunk_count": 0, "categories": {}, "documents": []})


@app.post("/api/v2/corpus/ingest-deposits")
@_require_admin
def v2_ingest_deposits():
    results = ingest_deposited_documents()
    changed_ids = _extract_document_ids(
        [item for item in results if item.get("status") in {"ingested", "updated", "tags_updated"}]
    )
    if changed_ids:
        _trigger_vector_sync("deposit ingestion", document_ids=changed_ids)
    return jsonify({"results": results, "status": get_db().stats()})


@app.post("/api/v2/corpus/upload")
@_require_admin
def v2_upload_document():
    files = request.files.getlist("file")
    if not files or not any(f.filename for f in files):
        return jsonify({"error": "Choose one or more PDF, DOCX, TXT, or MD files to upload."}), 400

    tag_overrides: dict[str, str] = {}
    for key in ("jurisdiction", "deal_stance", "deal_structure"):
        val = request.form.get(key, "").strip()
        if val:
            tag_overrides[key] = val

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    for uploaded in files:
        if not uploaded.filename:
            continue
        filename = secure_filename(uploaded.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            errors.append({"file": filename, "error": "Unsupported file type"})
            continue
        target = UPLOAD_DIR / filename
        uploaded.save(target)
        try:
            result = get_db().upsert_document(target, tag_overrides=tag_overrides or None)
        except Exception:
            logger.warning("Upload ingestion failed for %s: %s", filename, traceback.format_exc())
            errors.append({"file": filename, "error": "Unexpected ingestion error. Check server logs."})
            continue
        if result.get("status") == "error":
            errors.append({"file": filename, "error": result.get("error", result.get("reason", "Ingestion failed"))})
            continue
        results.append(result)

    changed_ids = _extract_document_ids(
        [item for item in results if item.get("status") in {"ingested", "updated", "tags_updated"}]
    )
    if changed_ids:
        _trigger_vector_sync("manual upload", document_ids=changed_ids)

    return jsonify({"results": results, "errors": errors, "status": get_db().stats()})


@app.delete("/api/v2/corpus/document/<int:doc_id>")
@_require_admin
def v2_delete_document(doc_id: int):
    result = get_db().delete_document(doc_id)
    if "error" in result:
        return jsonify(result), 404
    try:
        from scripts.vector_store import get_vector_store

        removed = get_vector_store().remove_document(doc_id)
        result["vectors_removed"] = removed
    except Exception:
        logger.warning("Vector delete failed for document %s: %s", doc_id, traceback.format_exc())
    return jsonify(result)


@app.post("/api/v2/corpus/document/<int:doc_id>/tags")
@_require_admin
def v2_update_tags(doc_id: int):
    body = request.get_json(silent=True) or {}
    tags = {}
    for key in ("jurisdiction", "deal_stance", "deal_structure"):
        if key in body:
            tags[key] = str(body[key]).strip()
    if not tags:
        return jsonify({"error": "Provide at least one tag: jurisdiction, deal_stance, deal_structure"}), 400
    result = get_db().update_document_tags(doc_id, tags)
    if "error" in result:
        return jsonify(result), 404
    _trigger_vector_sync(f"tag update doc={doc_id}", document_ids=[doc_id])
    return jsonify(result)


@app.get("/api/v2/retrieve")
@_require_admin
def v2_retrieve():
    query = request.args.get("q", "")
    category = request.args.get("category") or None
    return jsonify({"results": get_db().retrieve(query, top_k=10, category=category)})


@app.post("/api/v2/analyze")
def v2_analyze():
    payload = request.get_json(silent=True) or {}
    contract = str(payload.get("contract", ""))
    session_id = str(payload.get("session_id", ""))
    runtime_mode = str(payload.get("mode", "")).strip().lower() or None
    session_context = _get_session_docs(session_id) if session_id else []
    try:
        return jsonify(
            analyze_contract_v2(
                contract,
                session_context=session_context,
                runtime_mode=runtime_mode,
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/session/upload")
def session_upload():
    uploaded = request.files.get("file")
    session_id = request.form.get("session_id", "")
    if not session_id:
        return jsonify({"error": "Session ID is required."}), 400
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Choose a PDF, DOCX, TXT, or MD file."}), 400
    filename = secure_filename(uploaded.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({"error": "Only PDF, DOCX, TXT, and MD files are supported."}), 400

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        uploaded.save(tmp)
        tmp_path = Path(tmp.name)

    try:
        lc_docs = extract_text(tmp_path)
        full_text = "\n".join(doc.page_content for doc in lc_docs)
        if not full_text or len(full_text.strip()) < 50:
            return jsonify({"error": "Could not extract enough text from the file."}), 400
        classification = classify_document(filename, full_text)
        category = classification["category"]
        doc_type = classification["document_type"]

        splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=180)
        chunks = splitter.split_text(full_text)

        session_chunks = []
        for i, chunk in enumerate(chunks):
            session_chunks.append({
                "text": normalize_ws(chunk),
                "title": filename,
                "category": category,
                "page": i + 1,
                "source_system": "session_upload",
                "score": 0,
            })

        doc_info = {
            "filename": filename,
            "category": category,
            "document_type": doc_type,
            "chunk_count": len(session_chunks),
            "chunks": session_chunks,
        }
        if not _add_session_doc(session_id, doc_info):
            return jsonify({"error": f"Session document limit reached ({MAX_SESSION_DOCS} max). Remove documents or start a new session."}), 400
        return jsonify(doc_info)
    except Exception as exc:
        logger.warning("Session upload parse failed for %s: %s", filename, traceback.format_exc())
        return jsonify({"error": f"Failed to parse document: {exc}"}), 400
    finally:
        tmp_path.unlink(missing_ok=True)


def _extract_deal_details(session_id: str) -> dict[str, str]:
    docs = _get_session_docs(session_id)
    if not docs:
        return {}

    full_text = "\n".join(
        chunk["text"] for doc in docs for chunk in doc.get("chunks", [])
    )
    if not full_text.strip():
        return {}

    details: dict[str, str] = {}
    text_lower = full_text.lower()

    tx_patterns = [
        (r"(?:reverse\s+)?triangular\s+merger", "Reverse triangular merger"),
        (r"stock\s+purchase", "Stock purchase"),
        (r"asset\s+purchase", "Asset purchase"),
        (r"merger\s+(?:agreement|transaction)", "Merger"),
        (r"share\s+exchange", "Share exchange"),
        (r"tender\s+offer", "Tender offer"),
    ]
    for pat, label in tx_patterns:
        if re.search(pat, text_lower):
            details["transaction_type"] = label
            break

    preamble_m = re.search(
        r'(?:entered\s+into\s+)?(?:by\s+and\s+(?:between|among)\s+)(.{10,400}?)(?:\.\s|\n\n)',
        full_text, re.IGNORECASE | re.DOTALL)
    preamble_entities: list[str] = []
    if preamble_m:
        raw = preamble_m.group(1)
        preamble_entities = [
            e.strip().rstrip(",. ")
            for e in re.split(r',\s+(?:and\s+)?|\s+and\s+', raw)
            if re.search(r'(?:Inc|LLC|Corp|Company|Ltd|LP|Holdings)', e, re.IGNORECASE)
        ]

    party_patterns = [
        ("buyer_name", [
            r'(?:buyer|purchaser|parent|acqui(?:rer|ror))[,\s]*(?:a\s+\w+\s+(?:corporation|llc|inc|company))?\s*\("([^"]{3,80})"\)',
            r'"([^"]{3,80})"\s*\((?:the\s+)?"?(?:buyer|purchaser|parent|acqui(?:rer|ror))"?\)',
        ]),
        ("seller_name", [
            r'(?:seller|target|company)[,\s]*(?:a\s+\w+\s+(?:corporation|llc|inc|company))?\s*\("([^"]{3,80})"\)',
            r'"([^"]{3,80})"\s*\((?:the\s+)?"?(?:seller|target|company)"?\)',
        ]),
        ("merger_sub_name", [
            r'(?:merger\s+sub(?:sidiary)?|acquisition\s+(?:sub|vehicle))[,\s]*(?:a\s+\w+\s+(?:corporation|llc|inc|company))?\s*\("([^"]{3,80})"\)',
            r'"([^"]{3,80})"\s*\((?:the\s+)?"?(?:merger\s+sub|acquisition\s+sub)"?\)',
        ]),
    ]
    for field, patterns in party_patterns:
        for pat in patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                details[field] = m.group(1).strip().rstrip(",. ")
                break

    if preamble_entities:
        if "buyer_name" not in details and len(preamble_entities) >= 1:
            details["buyer_name"] = preamble_entities[0]
        if "merger_sub_name" not in details and len(preamble_entities) >= 2:
            mid = preamble_entities[1]
            if re.search(r'merger\s*sub|acquisition', mid, re.IGNORECASE):
                details["merger_sub_name"] = mid
        if "seller_name" not in details:
            details["seller_name"] = preamble_entities[-1]

    price_patterns = [
        r'(?:(?:purchase|merger|aggregate)\s+(?:price|consideration)|(?:consideration\s+(?:of|equal\s+to)))\s*(?:(?:is|shall\s+be|of|equal\s+to|equals)\s+)?[\$]?([\$]?[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|MM|M|B))?)',
        r'\$([\d,]+(?:\.\d+)?(?:\s*(?:million|billion|MM|M|B))?)\s*(?:in\s+cash\s+)?(?:at\s+closing|aggregate|purchase\s+price)',
    ]
    for pat in price_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if not val.startswith("$"):
                val = "$" + val
            details["purchase_price"] = val
            break

    wc_patterns = [
        r'(?:working\s+capital)\s+(?:adjustment|target|peg|amount)[\s:]*(?:of\s+)?\$?([\d][\d,\.]+(?:\s*(?:million|MM|M))?)',
        r'(?:working\s+capital)[^.]{0,200}?(?:target|peg)\s+(?:of\s+)?\$?([\d][\d,\.]+)',
    ]
    for pat in wc_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            details["working_capital"] = "$" + val if not val.startswith("$") else val
            break
    if "working_capital" not in details:
        m = re.search(r'(?:working\s+capital\s+adjustment)[^.]{5,300}', full_text, re.IGNORECASE)
        if m:
            details["working_capital"] = m.group(0).strip()[:200]

    escrow_patterns = [
        r'(?:escrow|holdback)[^.]{0,250}',
    ]
    for pat in escrow_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            details["escrow"] = m.group(0).strip()[:200]
            break

    indemnity_patterns = [
        r'(?:indemnif(?:y|ication))\s+cap[^.]{0,250}',
        r'(?:indemnif(?:y|ication))[^.]{0,120}(?:basket|cap|deductible)[^.]{0,150}',
    ]
    for pat in indemnity_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            details["indemnity_cap"] = m.group(0).strip()[:200]
            break

    survival_patterns = [
        r'(?:survival|survival\s+period)[^.]{0,250}',
        r'(?:representations|warranties)\s+(?:shall\s+)?surviv[^.]{0,250}',
    ]
    for pat in survival_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            details["survival_period"] = m.group(0).strip()[:200]
            break

    closing_patterns = [
        r'(?:closing\s+conditions?|conditions?\s+(?:to|precedent))[^.]{0,300}',
    ]
    for pat in closing_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            details["closing_conditions"] = m.group(0).strip()[:250]
            break

    gov_patterns = [
        r'(?:governed?\s+by|governing\s+law)[^.]{0,100}(?:laws?\s+of\s+(?:the\s+)?(?:State\s+of\s+)?)([\w\s]+?)(?:\.|,|;|\s+without)',
        r'(?:laws?\s+of\s+(?:the\s+)?(?:State\s+of\s+)?)([\w]+)\s+(?:shall\s+)?govern',
    ]
    for pat in gov_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            details["governing_law"] = m.group(1).strip()
            break

    business_patterns = [
        r'(?:target|company|seller)\s+(?:is\s+)?(?:engaged?\s+in|(?:a|the)\s+(?:provider|developer|operator|manufacturer|supplier)\s+of)\s+([^.]{10,200})',
        r'(?:business\s+of\s+(?:the\s+)?(?:target|company|seller))\s+(?:is|consists?\s+of)\s+([^.]{10,200})',
    ]
    for pat in business_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            details["target_business"] = m.group(1).strip()[:200]
            break

    special_keywords = [
        "open.?source", "key.?(?:customer|employee)", "tax.?clearance",
        "regulatory.?approv", "antitrust", "hsr", "hart.?scott",
        "environmental", "litigation", "ip.?(?:review|infringement)",
        "consent", "change.?of.?control", "earn.?out",
    ]
    found_special = []
    for kw in special_keywords:
        if re.search(kw, text_lower):
            found_special.append(re.sub(r'[.?]', ' ', kw).strip().title())
    if found_special:
        details["special_issues"] = "; ".join(found_special[:6])

    return details


@app.post("/api/session/extract-details")
def session_extract_details():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", ""))
    if not session_id:
        return jsonify({"error": "Session ID is required."}), 400
    details = _extract_deal_details(session_id)
    return jsonify({"details": details, "fields_found": len(details)})


@app.get("/api/edgar/search")
@_require_admin
def edgar_search():
    query = request.args.get("q", '"agreement and plan of merger"')
    try:
        max_results = min(max(int(request.args.get("max", "10")), 1), 20)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid max parameter."}), 400
    start_date = request.args.get("start_date", "2022-01-01")
    end_date = request.args.get("end_date", DEFAULT_EDGAR_END_DATE)
    results = search_edgar_filings(query=query, start_date=start_date, end_date=end_date, max_results=max_results)
    if results and "error" in results[0]:
        return jsonify({"error": results[0]["error"], "results": [], "query": query}), 502
    return jsonify({"results": results, "query": query})


@app.post("/api/edgar/ingest")
@_require_admin
def edgar_ingest():
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query", '"agreement and plan of merger"'))
    try:
        max_filings = min(max(int(payload.get("max_filings", 5)), 1), 10)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid max_filings parameter."}), 400
    start_date = str(payload.get("start_date", "2022-01-01"))
    end_date = str(payload.get("end_date", DEFAULT_EDGAR_END_DATE))
    result = search_and_ingest(query=query, max_filings=max_filings, start_date=start_date, end_date=end_date)
    if result.get("status") == "error":
        return jsonify(result), 502
    edgar_doc_ids = _extract_document_ids(result.get("ingested", []))
    if edgar_doc_ids:
        _trigger_vector_sync("edgar ingestion", document_ids=edgar_doc_ids)
    return jsonify(result)


@app.post("/api/v2/template/generate")
def v2_template_generate():
    payload = request.get_json(silent=True) or {}
    details = payload.get("details") or {}
    runtime_mode = str(payload.get("mode", "")).strip().lower() or None
    if not isinstance(details, dict):
        return jsonify({"error": "Template details must be an object."}), 400
    return jsonify(
        generate_agreement_v2(
            {str(k): str(v) for k, v in details.items()},
            runtime_mode=runtime_mode,
        )
    )


@app.get("/api/datasets/status")
@_require_admin
def datasets_status():
    return jsonify(dataset_summary())


@app.post("/api/datasets/maud/ingest")
@_require_admin
def datasets_maud_ingest():
    current = get_ingest_status("maud")
    if current.get("status") in ("downloading", "ingesting"):
        return jsonify({"error": "MAUD ingestion already in progress"}), 409

    payload = request.get_json(silent=True) or {}
    try:
        max_contracts = min(max(int(payload.get("max_contracts", 20)), 1), 153)
    except (TypeError, ValueError):
        return jsonify({"error": "max_contracts must be a number"}), 400

    raw_splits = payload.get("splits") or ["train"]
    if not isinstance(raw_splits, list):
        return jsonify({"error": "splits must be an array"}), 400
    valid_splits = [s for s in raw_splits if isinstance(s, str) and s in ("train", "dev", "test")]
    if not valid_splits:
        valid_splits = ["train"]

    def run_maud():
        result = ingest_maud(max_contracts=max_contracts, splits=valid_splits)
        maud_doc_ids = _extract_document_ids(result.get("results", []))
        if result.get("status") == "complete" and maud_doc_ids:
            _trigger_vector_sync("maud ingestion", document_ids=maud_doc_ids)

    thread = threading.Thread(target=run_maud, daemon=True)
    thread.start()
    return jsonify({"status": "started", "max_contracts": max_contracts, "splits": valid_splits})


@app.post("/api/datasets/cuad/ingest")
@_require_admin
def datasets_cuad_ingest():
    current = get_ingest_status("cuad")
    if current.get("status") in ("downloading", "ingesting"):
        return jsonify({"error": "CUAD ingestion already in progress"}), 409

    payload = request.get_json(silent=True) or {}
    try:
        max_contracts = min(max(int(payload.get("max_contracts", 20)), 1), 510)
    except (TypeError, ValueError):
        return jsonify({"error": "max_contracts must be a number"}), 400

    def run_cuad():
        result = ingest_cuad(max_contracts=max_contracts)
        cuad_doc_ids = _extract_document_ids(result.get("results", []))
        if result.get("status") == "complete" and cuad_doc_ids:
            _trigger_vector_sync("cuad ingestion", document_ids=cuad_doc_ids)

    thread = threading.Thread(target=run_cuad, daemon=True)
    thread.start()
    return jsonify({"status": "started", "max_contracts": max_contracts})


@app.get("/api/datasets/maud/status")
@_require_admin
def datasets_maud_status():
    return jsonify(get_ingest_status("maud"))


@app.get("/api/datasets/cuad/status")
@_require_admin
def datasets_cuad_status():
    return jsonify(get_ingest_status("cuad"))


def _startup_vector_sync():
    try:
        from scripts.vector_store import get_vector_store
        store = get_vector_store()
        if store.count() == 0:
            state = _start_vector_sync("startup sync", trigger="startup")
            logger.info("Startup vector sync triggered: %s", state.get("status"))
        else:
            logger.info("ChromaDB already has %d vectors, skipping startup sync", store.count())
    except Exception:
        logger.warning("Startup vector sync skipped (non-fatal): %s", traceback.format_exc())


_sync_thread = threading.Thread(target=_startup_vector_sync, daemon=True)
_sync_thread.start()


@app.get("/api/v2/pipeline/status")
def v2_pipeline_status():
    try:
        status = pipeline_status()
        if "llm" in status:
            status["llm"].pop("ollama_url", None)
        return jsonify(status)
    except Exception as exc:
        logger.warning("Pipeline status failed: %s", exc)
        return jsonify({"error": "Pipeline status unavailable"}), 500


@app.get("/api/v2/runtime/status")
@_require_admin
def v2_runtime_status():
    return jsonify(runtime_control_status())


@app.post("/api/v2/runtime/mode")
@_require_admin
def v2_runtime_mode():
    payload = request.get_json(silent=True) or {}
    requested_mode = str(payload.get("mode", "")).strip().lower()
    if requested_mode in {"", "clear", "configured", "unset"}:
        forced = set_forced_runtime_mode(None)
    elif requested_mode in {"auto", "llm", "deterministic"}:
        forced = set_forced_runtime_mode(requested_mode)
    else:
        return jsonify({"error": "mode must be one of: auto, llm, deterministic, clear"}), 400

    status = runtime_control_status()
    status["forced_mode"] = forced
    return jsonify(status)


@app.post("/api/v2/vectors/sync")
@_require_admin
def v2_vector_sync():
    try:
        state = _start_vector_sync("manual full sync", trigger="manual")
        code = 202 if state.get("status") in {"started", "running"} else 200
        return jsonify(state), code
    except Exception as exc:
        logger.error("Vector sync failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.get("/api/v2/vectors/sync/status")
@_require_admin
def v2_vector_sync_status():
    return jsonify(_vector_sync_snapshot())


@app.post("/api/v2/vectors/clear")
@_require_admin
def v2_vector_clear():
    try:
        from scripts.vector_store import get_vector_store
        get_vector_store().clear()
        return jsonify({"status": "cleared"})
    except Exception as exc:
        logger.error("Vector clear failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.get("/api/v2/llm/status")
def v2_llm_status():
    try:
        from scripts.llm_provider import get_llm
        status = get_llm().model_status()
        status.pop("ollama_url", None)
        return jsonify(status)
    except Exception as exc:
        return jsonify({"ollama_available": False, "mode": "deterministic"})


# ── Demo mode guard ──────────────────────────────────────────────────────────

DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() in ("true", "1", "yes")
HUB_ENABLED = os.environ.get("HUB_ENABLED", "true").lower() not in ("false", "0", "no")
INPUT_MAX_CHARS = 500


def _demo_gate(f):
    """Block corpus ingest/upload routes in DEMO_MODE."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if DEMO_MODE:
            return jsonify({"error": "Corpus ingest disabled in demo mode"}), 403
        return f(*args, **kwargs)
    return wrapper


def _hub_enabled(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not HUB_ENABLED:
            return jsonify({"error": "Hub is currently disabled", "code": "HUB_DISABLED"}), 503
        return f(*args, **kwargs)
    return wrapper


def _pii_screen_request(text: str):
    """Return 400 JSON response if text fails PII firewall, else None."""
    from scripts.pii_firewall import screen
    blocked, reason = screen(text)
    if blocked:
        return jsonify({"error": "Input blocked by content policy", "code": "PII_FILTER", "detail": reason}), 400
    return None


def _check_input_length(text: str):
    if len(text) > INPUT_MAX_CHARS:
        return jsonify({"error": f"Query exceeds {INPUT_MAX_CHARS} character limit", "code": "LENGTH_LIMIT"}), 400
    return None


# Wrap admin ingest routes with demo gate
_original_edgar_ingest = app.view_functions.get("edgar_ingest")
if _original_edgar_ingest:
    app.view_functions["edgar_ingest"] = _demo_gate(_original_edgar_ingest)

_original_v2_upload = app.view_functions.get("v2_upload_document")
if _original_v2_upload:
    app.view_functions["v2_upload_document"] = _demo_gate(_original_v2_upload)

_original_ingest_deposits = app.view_functions.get("v2_ingest_deposits")
if _original_ingest_deposits:
    app.view_functions["v2_ingest_deposits"] = _demo_gate(_original_ingest_deposits)


# ── Consent gate ─────────────────────────────────────────────────────────────

import hashlib as _hashlib
import hmac as _hmac
_CONSENT_SECRET = os.environ.get("CONSENT_SECRET") or _secrets.token_hex(32)


def _make_consent_token(ip: str) -> str:
    msg = f"{ip}:{date.today().isoformat()}"
    return _hmac.new(_CONSENT_SECRET.encode(), msg.encode(), _hashlib.sha256).hexdigest()[:32]


def _valid_consent_token(token: str) -> bool:
    if not DEMO_MODE:
        return True
    ip = request.remote_addr or ""
    expected = _make_consent_token(ip)
    return _hmac.compare_digest(token or "", expected)


@app.post("/api/consent/accept")
def consent_accept():
    ip = request.remote_addr or ""
    token = _make_consent_token(ip)
    return jsonify({"token": token, "accepted": True})


# ── Hub page ──────────────────────────────────────────────────────────────────

@app.get("/hub")
@app.get("/review")
def hub_page():
    if not HUB_ENABLED:
        return redirect("/")
    return render_template("review.html")


# ── Hub in-memory session cache (supplements Postgres for fast status polls) ──

_hub_sessions: dict[str, dict[str, Any]] = {}
_hub_sessions_lock = threading.Lock()


def _hub_store(session_id: str, data: dict[str, Any]) -> None:
    with _hub_sessions_lock:
        _hub_sessions[session_id] = data


def _hub_load(session_id: str) -> dict[str, Any] | None:
    with _hub_sessions_lock:
        return _hub_sessions.get(session_id)


# ── Hub submission routes ─────────────────────────────────────────────────────

def _run_hub_background(mode: str, kwargs: dict[str, Any], session_id_holder: list[str]) -> None:
    """Run hub pipeline in a thread; stores result in _hub_sessions."""
    from scripts.hub_pipeline import run_hub_session
    try:
        result = run_hub_session(mode=mode, **kwargs)
        sid = result["session_id"]
        session_id_holder.append(sid)
        _hub_store(sid, result)
    except Exception:
        logger.exception("Hub background task failed")


def _submit_hub(mode: str) -> Response:
    if not HUB_ENABLED:
        return jsonify({"error": "Hub disabled"}), 503

    sub_flag = f"HUB_{mode.upper()}_ENABLED"
    if os.environ.get(sub_flag, "true").lower() in ("false", "0", "no"):
        return jsonify({"error": f"Mode {mode} is disabled"}), 503

    consent_token = request.headers.get("X-Consent-Token", "")
    if DEMO_MODE and not _valid_consent_token(consent_token):
        return jsonify({"error": "Consent required", "code": "CONSENT_REQUIRED"}), 403

    # Input validation
    prompt = request.form.get("prompt", "").strip()
    if prompt:
        err = _check_input_length(prompt)
        if err:
            return err
        err = _pii_screen_request(prompt)
        if err:
            return err

    posture = request.form.get("posture", "neutral")
    doc_type = request.form.get("doc_type", "NDA")
    governing_law = request.form.get("governing_law", "Delaware")

    file_bytes: bytes | None = None
    filename: str | None = None
    if mode in ("revise", "review"):
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "File required for this mode"}), 400
        max_bytes = int(os.environ.get("HUB_MAX_BYTES", str(25 * 1024 * 1024)))
        raw = uploaded.read()
        if len(raw) > max_bytes:
            return jsonify({"error": f"File exceeds {max_bytes // (1024*1024)} MB limit"}), 400
        file_bytes = raw
        filename = secure_filename(uploaded.filename)

    db_url = os.environ.get("DATABASE_URL", "")
    kwargs: dict[str, Any] = {
        "posture": posture,
        "doc_type": doc_type,
        "governing_law": governing_law,
        "database_url": db_url or None,
    }
    if prompt:
        kwargs["prompt"] = prompt
    if file_bytes:
        kwargs["file_bytes"] = file_bytes
        kwargs["filename"] = filename

    # Run synchronously for simplicity; in production wrap in a Cloud Run Job
    from scripts.hub_pipeline import run_hub_session
    try:
        result = run_hub_session(mode=mode, **kwargs)
        _hub_store(result["session_id"], result)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Hub %s failed", mode)
        return jsonify({"error": str(exc)}), 500


@app.post("/api/v2/hub/generate")
@_hub_enabled
def hub_generate():
    return _submit_hub("generate")


@app.post("/api/v2/hub/revise")
@_hub_enabled
def hub_revise():
    return _submit_hub("revise")


@app.post("/api/v2/hub/review")
@_hub_enabled
def hub_review():
    return _submit_hub("review")


# ── Context attach ────────────────────────────────────────────────────────────

@app.post("/api/v2/context/attach")
@_hub_enabled
def hub_context_attach():
    consent_token = request.headers.get("X-Consent-Token", "")
    if DEMO_MODE and not _valid_consent_token(consent_token):
        return jsonify({"error": "Consent required"}), 403

    session_id = request.args.get("session_id") or request.form.get("session_id", "")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    content = request.form.get("content", "").strip() or None
    uploaded = request.files.get("file")
    file_bytes: bytes | None = None
    filename: str | None = None
    if uploaded and uploaded.filename:
        file_bytes = uploaded.read()
        filename = secure_filename(uploaded.filename)

    from scripts.context_loader import attach_context
    result = attach_context(session_id, content=content, file_bytes=file_bytes, filename=filename)
    code = 200 if result.get("status") == "ok" else 400
    return jsonify(result), code


# ── Hub status ────────────────────────────────────────────────────────────────

@app.get("/api/v2/hub/<session_id>/status")
def hub_status(session_id: str):
    data = _hub_load(session_id)
    if data:
        return jsonify({"session_id": session_id, "status": data.get("status", "ready"),
                        "changes": data.get("changes", []), "mode": data.get("mode"),
                        "posture": data.get("posture"), "draft_text": data.get("draft_text", "")})
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            import psycopg
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status, mode, posture FROM hub_sessions WHERE id = %s",
                        (session_id,),
                    )
                    row = cur.fetchone()
            if row:
                return jsonify({"session_id": session_id, "status": row[0], "mode": row[1], "posture": row[2]})
        except Exception as exc:
            logger.warning("Hub status DB lookup failed: %s", exc)
    return jsonify({"error": "Session not found"}), 404


# ── Per-change actions ────────────────────────────────────────────────────────

@app.route("/api/v2/hub/<session_id>/changes/<change_id>", methods=["PATCH"])
def hub_change_action(session_id: str, change_id: str):
    consent_token = request.headers.get("X-Consent-Token", "")
    if DEMO_MODE and not _valid_consent_token(consent_token):
        return jsonify({"error": "Consent required"}), 403

    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "")
    edited_text = payload.get("edited_text")

    valid_actions = {"accept", "reject", "edit", "dismiss"}
    if action not in valid_actions:
        return jsonify({"error": f"action must be one of {valid_actions}"}), 400

    # Update in-memory session
    data = _hub_load(session_id)
    if data:
        for c in data.get("changes", []):
            if c.get("id") == change_id or c.get("change_id") == change_id:
                c["current_action"] = action
                if edited_text is not None:
                    c["current_text"] = edited_text

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            import psycopg
            from datetime import datetime, timezone as tz
            update_sql = """
                UPDATE hub_changes
                SET current_action = %s,
                    current_text = COALESCE(%s, current_text)
                WHERE id = %s AND session_id = %s
            """
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(update_sql, (action, edited_text, change_id, session_id))
                    # Bump last_activity_at on the session
                    cur.execute(
                        "UPDATE hub_sessions SET last_activity_at = NOW() WHERE id = %s",
                        (session_id,),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("Hub change action DB update failed: %s", exc)

    return jsonify({"session_id": session_id, "change_id": change_id, "action": action})


# ── Anchored chat ─────────────────────────────────────────────────────────────

@app.post("/api/v2/hub/<session_id>/ask")
@_hub_enabled
def hub_ask(session_id: str):
    consent_token = request.headers.get("X-Consent-Token", "")
    if DEMO_MODE and not _valid_consent_token(consent_token):
        return jsonify({"error": "Consent required"}), 403

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    clause_anchor = str(payload.get("clause_anchor", "")).strip()

    if not question:
        return jsonify({"error": "question is required"}), 400

    err = _check_input_length(question)
    if err:
        return err
    err = _pii_screen_request(question)
    if err:
        return err

    from scripts.hub_chat import ask_clause

    def generate():
        yield "data: {\"meta\": \"start\"}\n\n"
        for chunk in ask_clause(session_id, clause_anchor, question):
            import json as _json
            yield f"data: {_json.dumps({'token': chunk})}\n\n"
        yield "data: {\"done\": true}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Bake (save & download) ────────────────────────────────────────────────────

@app.post("/api/v2/hub/<session_id>/bake")
@_hub_enabled
def hub_bake(session_id: str):
    consent_token = request.headers.get("X-Consent-Token", "")
    if DEMO_MODE and not _valid_consent_token(consent_token):
        return jsonify({"error": "Consent required"}), 403

    data = _hub_load(session_id)
    if not data:
        return jsonify({"error": "Session not found or expired"}), 404

    from scripts.hub_export import bake_session
    try:
        artifacts = bake_session(
            session_id=session_id,
            draft_text=data.get("draft_text", ""),
            changes=data.get("changes", []),
            decisions=data.get("decisions", []),
            posture=data.get("posture", "neutral"),
            gcs_prefix=data.get("gcs_prefix"),
        )
        # Store artifact refs in session so download links work
        if data:
            data["artifacts"] = artifacts
        return jsonify({k: v for k, v in artifacts.items() if not k.endswith("_bytes")})
    except Exception as exc:
        logger.exception("Hub bake failed for session %s", session_id)
        return jsonify({"error": str(exc)}), 500


@app.get("/api/v2/hub/<session_id>/download/<artifact_name>")
def hub_download(session_id: str, artifact_name: str):
    safe_names = {"redline.docx", "clean.docx", "memo.docx", "register.json"}
    if artifact_name not in safe_names:
        return jsonify({"error": "Unknown artifact"}), 404

    data = _hub_load(session_id)
    if not data or "artifacts" not in data:
        return jsonify({"error": "Session not found or not yet baked"}), 404

    key = artifact_name + "_bytes"
    blob = data["artifacts"].get(key)
    if not blob:
        # Try GCS redirect
        gcs_uri = data["artifacts"].get(artifact_name, "")
        if gcs_uri:
            # In production use a signed URL; for now redirect to a placeholder
            return jsonify({"gcs_uri": gcs_uri}), 200
        return jsonify({"error": "Artifact not available"}), 404

    mime = "application/json" if artifact_name.endswith(".json") else \
           "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(
        blob,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename={artifact_name}"},
    )


# ── Hub delete ────────────────────────────────────────────────────────────────

@app.delete("/api/v2/hub/<session_id>")
def hub_delete(session_id: str):
    consent_token = request.headers.get("X-Consent-Token", "")
    if DEMO_MODE and not _valid_consent_token(consent_token):
        return jsonify({"error": "Consent required"}), 403

    with _hub_sessions_lock:
        _hub_sessions.pop(session_id, None)

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            import psycopg
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM hub_sessions WHERE id = %s", (session_id,))
                conn.commit()
        except Exception as exc:
            logger.warning("Hub delete DB failed for session %s: %s", session_id, exc)

    try:
        from scripts.session_memory import get_session_memory
        get_session_memory(session_id).clear()
    except Exception:
        pass

    return jsonify({"deleted": True, "session_id": session_id})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=port, debug=debug)
