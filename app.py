from __future__ import annotations

import os

from flask import Flask, Response, jsonify, render_template, request

from scripts.ma_crag_engine import (
    SAMPLE_CONTRACT,
    TEMPLATE_QUESTIONS,
    analyze_contract,
    generate_agreement,
    retrieve,
)


app = Flask(__name__)


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=port, debug=debug)