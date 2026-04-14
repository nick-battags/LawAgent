"""Database-backed LangChain Corrective RAG version for LawAgent."""

from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from scripts.ma_corpus_db import CorpusDatabase, normalize_ws
from scripts.ma_crag_engine import SAMPLE_CONTRACT, analyze_contract, generate_agreement, retrieve as static_retrieve


def build_context(results: list[dict[str, Any]], limit: int = 4200) -> str:
    parts = []
    total = 0
    for result in results:
        snippet = normalize_ws(result["text"])
        label = f"[{result['title']} | {result['category']} | page {result['page']}] {snippet}"
        if total + len(label) > limit:
            break
        parts.append(label)
        total += len(label)
    return "\n\n".join(parts)


def grade_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = [
        Document(
            page_content=result["text"],
            metadata={
                "title": result["title"],
                "category": result["category"],
                "score": result["score"],
                "page": result["page"],
            },
        )
        for result in results
    ]
    relevant = []
    query_terms = {term for term in query.lower().split() if len(term) > 3}
    for doc, result in zip(docs, results):
        text = doc.page_content.lower()
        overlap = sum(1 for term in query_terms if term in text)
        if overlap or result["score"] >= 2:
            result = dict(result)
            result["grade"] = "relevant"
            result["grade_reason"] = f"Matched {max(overlap, result['score'])} query/corpus signals."
            relevant.append(result)
    return relevant


def corrective_query(original_query: str, contract_text: str) -> str:
    lowered = contract_text.lower()
    expansions = ["M&A due diligence", "acquisition agreement", "risk allocation"]
    for phrase in ["indemnification", "escrow", "assignment", "change of control", "closing conditions", "employment", "intellectual property", "asset acquisition", "ancillary agreements"]:
        if phrase in lowered and phrase not in original_query.lower():
            expansions.append(phrase)
    return f"{original_query} {' '.join(expansions)}"


def retrieve_from_corpus(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    db = CorpusDatabase()
    initial = db.retrieve(query, top_k=top_k)
    graded = grade_results(query, initial)
    if graded:
        return graded
    rewritten = f"{query} merger acquisition due diligence checklist representations warranties indemnification consents ancillary"
    return grade_results(rewritten, db.retrieve(rewritten, top_k=top_k))


def analyze_contract_v2(contract_text: str) -> dict[str, Any]:
    base = analyze_contract(contract_text or SAMPLE_CONTRACT)
    query = corrective_query(
        "contract issue spotting missing clauses corrective drafting guidance",
        contract_text or SAMPLE_CONTRACT,
    )
    corpus_results = retrieve_from_corpus(query, top_k=10)
    context = build_context(corpus_results)

    for issue in base["issues"]:
        topic_query = f"{issue['title']} {issue['why_it_matters']} {issue['corrective_action']}"
        topical = retrieve_from_corpus(topic_query, top_k=2)
        if topical:
            issue["corpus_support"] = [
                {
                    "title": item["title"],
                    "category": item["category"],
                    "source_system": item["source_system"],
                    "page": item["page"],
                    "excerpt": normalize_ws(item["text"])[:520],
                }
                for item in topical
            ]

    base["summary"]["version"] = "V2 database-backed LangChain CRAG"
    base["summary"]["corpus_chunks_used"] = len(corpus_results)
    base["summary"]["crag_pipeline"] = [
        "Deposit and classify user-provided training documents in the central corpus database.",
        "Split documents into LangChain Document chunks for retrieval.",
        "Retrieve matching M&A corpus excerpts from the database.",
        "Grade retrieved excerpts for relevance and rewrite the query when retrieval is weak.",
        "Correct contract issues using the original checklist plus retrieved corpus support.",
    ]
    base["corpus_results"] = corpus_results
    base["corpus_context_preview"] = context[:1800]
    base["architecture"] = {
        "variation": "v2_corpus_crag",
        "database": "PostgreSQL via DATABASE_URL when available, SQLite fallback for GitHub/local replication",
        "pipeline_shared_with_original": ["ingestion", "classification", "chunking", "retrieval", "grading", "correction", "generation"],
        "security": [
            "No third-party model API is required for the demo path.",
            "Uploaded documents remain in the project database/local filesystem.",
            "Only text extracted from user-deposited documents is retrieved into answers.",
        ],
    }
    return base


def generate_agreement_v2(details: dict[str, str]) -> dict[str, Any]:
    draft = generate_agreement(details)
    query = " ".join(str(value) for value in details.values()) or "M&A agreement drafting template"
    corpus_results = retrieve_from_corpus(query, top_k=8)
    draft["corpus_results"] = corpus_results
    draft["corpus_context_preview"] = build_context(corpus_results, limit=2200)
    draft["version"] = "V2 database-backed LangChain CRAG"
    return draft


def corpus_status() -> dict[str, Any]:
    db = CorpusDatabase()
    return db.stats()


def ingest_deposited_documents() -> list[dict[str, Any]]:
    db = CorpusDatabase()
    return db.ingest_deposit_dirs()