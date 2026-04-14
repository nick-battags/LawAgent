from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

import secrets as _secrets

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from scripts.ma_corpus_db import get_db, extract_text, classify_document, normalize_ws
from scripts.ma_crag_engine import (
    SAMPLE_CONTRACT,
    TEMPLATE_QUESTIONS,
    analyze_contract,
    generate_agreement,
    retrieve,
)
from scripts.ma_db_crag_engine import analyze_contract_v2, generate_agreement_v2, ingest_deposited_documents
from scripts.edgar_fetcher import search_edgar_filings, search_and_ingest

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
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.path, traceback.format_exc())
    return jsonify({"error": "Internal server error. Check logs for details."}), 500


@app.after_request
def add_dev_headers(response):
    if os.environ.get("NODE_ENV") != "production":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return render_template("index.html")


def _admin_authed() -> bool:
    if not ADMIN_PIN:
        return True
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
    return jsonify({"results": results, "status": get_db().stats()})


@app.post("/api/v2/corpus/upload")
@_require_admin
def v2_upload_document():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Choose a PDF, DOCX, TXT, or MD file to upload."}), 400
    filename = secure_filename(uploaded.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({"error": "Only PDF, DOCX, TXT, and MD files are supported."}), 400
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / filename
    uploaded.save(target)
    result = get_db().upsert_document(target)
    return jsonify({"result": result, "status": get_db().stats()})


@app.get("/api/v2/retrieve")
def v2_retrieve():
    query = request.args.get("q", "")
    category = request.args.get("category") or None
    return jsonify({"results": get_db().retrieve(query, top_k=10, category=category)})


@app.post("/api/v2/analyze")
def v2_analyze():
    payload = request.get_json(silent=True) or {}
    contract = str(payload.get("contract", ""))
    session_id = str(payload.get("session_id", ""))
    session_context = _get_session_docs(session_id) if session_id else []
    try:
        return jsonify(analyze_contract_v2(contract, session_context=session_context))
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

        from langchain_text_splitters import RecursiveCharacterTextSplitter
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
    end_date = request.args.get("end_date", "2025-12-31")
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
    end_date = str(payload.get("end_date", "2025-12-31"))
    result = search_and_ingest(query=query, max_filings=max_filings, start_date=start_date, end_date=end_date)
    if result.get("status") == "error":
        return jsonify(result), 502
    return jsonify(result)


@app.post("/api/v2/template/generate")
def v2_template_generate():
    payload = request.get_json(silent=True) or {}
    details = payload.get("details") or {}
    if not isinstance(details, dict):
        return jsonify({"error": "Template details must be an object."}), 400
    return jsonify(generate_agreement_v2({str(k): str(v) for k, v in details.items()}))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=port, debug=debug)
