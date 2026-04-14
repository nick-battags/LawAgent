from __future__ import annotations

import os
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


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
UPLOAD_DIR = Path("training_docs_inbox/uploads")
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


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
    return jsonify(CorpusDatabase().stats())


@app.post("/api/v2/corpus/ingest-deposits")
def v2_ingest_deposits():
    results = ingest_deposited_documents()
    return jsonify({"results": results, "status": CorpusDatabase().stats()})


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
    result = CorpusDatabase().upsert_document(target)
    return jsonify({"result": result, "status": CorpusDatabase().stats()})


@app.get("/api/v2/retrieve")
def v2_retrieve():
    query = request.args.get("q", "")
    category = request.args.get("category") or None
    return jsonify({"results": CorpusDatabase().retrieve(query, top_k=10, category=category)})


@app.post("/api/v2/analyze")
def v2_analyze():
    payload = request.get_json(silent=True) or {}
    contract = str(payload.get("contract", ""))
    try:
        return jsonify(analyze_contract_v2(contract))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


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