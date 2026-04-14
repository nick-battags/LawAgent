from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.utils import secure_filename

from scripts.ma_corpus_db import CorpusDatabase
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
UPLOAD_DIR = Path("training_docs_inbox/uploads")
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

_corpus_db: CorpusDatabase | None = None


def get_corpus_db() -> CorpusDatabase:
    global _corpus_db
    if _corpus_db is None:
        _corpus_db = CorpusDatabase()
    return _corpus_db


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
def v2_corpus_status():
    try:
        return jsonify(get_corpus_db().stats())
    except Exception as exc:
        logger.warning("Corpus status failed: %s", exc)
        return jsonify({"backend": "unavailable", "document_count": 0, "chunk_count": 0, "categories": {}, "documents": []})


@app.post("/api/v2/corpus/ingest-deposits")
def v2_ingest_deposits():
    results = ingest_deposited_documents()
    return jsonify({"results": results, "status": get_corpus_db().stats()})


@app.post("/api/v2/corpus/upload")
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
    result = get_corpus_db().upsert_document(target)
    return jsonify({"result": result, "status": get_corpus_db().stats()})


@app.get("/api/v2/retrieve")
def v2_retrieve():
    query = request.args.get("q", "")
    category = request.args.get("category") or None
    return jsonify({"results": get_corpus_db().retrieve(query, top_k=10, category=category)})


@app.post("/api/v2/analyze")
def v2_analyze():
    payload = request.get_json(silent=True) or {}
    contract = str(payload.get("contract", ""))
    try:
        return jsonify(analyze_contract_v2(contract))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/edgar/search")
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
