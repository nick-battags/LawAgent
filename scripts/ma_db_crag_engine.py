"""Database-backed Corrective RAG engine for LawAgent.

Uses the 2-model CRAG pipeline (Llama 3.1 grader + Command-R7B generator)
when Ollama is available, with automatic deterministic fallback.
ChromaDB provides vector retrieval; PostgreSQL remains the source of truth.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from scripts.ma_corpus_db import get_db, normalize_ws
from scripts.ma_crag_engine import (
    SAMPLE_CONTRACT,
    analyze_contract,
    generate_agreement,
)
from scripts.crag_pipeline import (
    retrieve_and_grade,
    generate_with_context,
    enhance_issue_with_llm,
    pipeline_status,
    resolve_runtime_mode,
)

logger = logging.getLogger(__name__)
PER_ISSUE_LLM_ENHANCEMENT = os.environ.get("LAWAGENT_ENABLE_PER_ISSUE_LLM_ENHANCEMENT", "false").strip().lower() in {"1", "true", "yes", "on"}


def build_context(results: list[dict[str, Any]], limit: int = 4200) -> str:
    parts: list[str] = []
    total = 0
    for result in results:
        snippet = normalize_ws(result.get("text", ""))
        label = (
            f"[{result.get('title', '')} | {result.get('category', '')} | "
            f"page {result.get('page', '')}] {snippet}"
        )
        if total + len(label) > limit:
            break
        parts.append(label)
        total += len(label)
    return "\n\n".join(parts)


def retrieve_from_corpus(
    query: str,
    top_k: int = 8,
    runtime_mode: str | None = None,
) -> list[dict[str, Any]]:
    try:
        result = retrieve_and_grade(query, top_k=top_k, mode=runtime_mode)
        return result["relevant"]
    except Exception:
        logger.exception("retrieve_from_corpus failed: %s", query[:200])
        return []


def analyze_contract_v2(
    contract_text: str,
    session_context: list[dict[str, Any]] | None = None,
    runtime_mode: str | None = None,
) -> dict[str, Any]:
    base = analyze_contract(contract_text or SAMPLE_CONTRACT)
    effective_mode = resolve_runtime_mode(runtime_mode)

    query = "contract issue spotting missing clauses corrective drafting guidance"
    try:
        crag_result = retrieve_and_grade(query, top_k=10, mode=runtime_mode)
    except Exception:
        logger.exception("CRAG retrieval failed; using empty results")
        crag_result = {
            "relevant": [],
            "query_history": [query],
            "retries": 0,
            "grader": "error",
            "mode": effective_mode,
            "total_candidates": 0,
        }

    corpus_results = crag_result["relevant"]

    session_chunks: list[dict[str, Any]] = []
    if session_context:
        for doc in session_context:
            session_chunks.extend(doc.get("chunks", []))

    combined_results = corpus_results + session_chunks
    context = build_context(combined_results)

    llm_analysis = generate_with_context(
        query,
        corpus_results,
        contract_text or SAMPLE_CONTRACT,
        mode=runtime_mode,
    )

    # Keep request latency bounded in auto mode: use deterministic grading for
    # per-issue support retrieval while still allowing top-level generation.
    per_issue_mode = "deterministic" if effective_mode == "auto" else runtime_mode

    for issue in base["issues"]:
        topic_query = (
            f"{issue['title']} {issue['why_it_matters']} {issue['corrective_action']}"
        )
        try:
            topical_result = retrieve_and_grade(topic_query, top_k=2, mode=per_issue_mode)
            topical = topical_result["relevant"]
        except Exception:
            topical = []

        if session_chunks:
            topic_lower = topic_query.lower()
            topic_terms = {t for t in topic_lower.split() if len(t) > 3}
            for chunk in session_chunks:
                chunk_text = chunk.get("text", "").lower()
                if any(term in chunk_text for term in topic_terms):
                    topical.append(chunk)

        if topical:
            issue["corpus_support"] = [
                {
                    "title": item.get("title", ""),
                    "category": item.get("category", ""),
                    "source_system": item.get("source_system", "session_upload"),
                    "page": item.get("page", ""),
                    "excerpt": normalize_ws(item.get("text", ""))[:520],
                }
                for item in topical
            ]

            if PER_ISSUE_LLM_ENHANCEMENT:
                llm_enhancement = enhance_issue_with_llm(
                    issue["title"],
                    issue.get("why_it_matters", ""),
                    topical,
                    mode=runtime_mode,
                )
                if llm_enhancement:
                    issue["llm_enhancement"] = llm_enhancement

    status = pipeline_status()

    base["summary"]["version"] = "V2 Corrective RAG - 2-model architecture"
    base["summary"]["corpus_chunks_used"] = len(combined_results)
    base["summary"]["session_chunks_used"] = len(session_chunks)
    base["summary"]["crag_retries"] = crag_result["retries"]
    base["summary"]["grader"] = crag_result["grader"]
    base["summary"]["runtime_mode"] = crag_result.get("mode", "auto")
    base["summary"]["generator"] = llm_analysis.get("generator", "deterministic")
    base["summary"]["crag_pipeline"] = [
        "Embed user query with nomic-embed-text and retrieve top-k vectors from ChromaDB.",
        "Grade each retrieved chunk with Llama 3.1 8B (strict JSON relevance scoring).",
        "If no relevant chunks pass grading, rewrite the query and retry (max 2 attempts).",
        "Pass approved chunks + contract text to Command-R7B for synthesis with citations.",
        "Merge LLM analysis into deterministic clause map and issue list.",
    ]
    base["summary"]["query_history"] = crag_result["query_history"]
    base["corpus_results"] = combined_results
    base["corpus_context_preview"] = context[:1800]

    if llm_analysis.get("analysis"):
        base["llm_analysis"] = llm_analysis

    base["architecture"] = {
        "variation": "v2_crag_2model",
        "grader": status["llm"]["grader_model"],
        "generator": status["llm"]["generator_model"],
        "embedding": status["vector_store"]["embedding"],
        "vector_count": status["vector_store"]["vector_count"],
        "mode": status["llm"]["mode"],
        "runtime_mode": crag_result.get("mode", status.get("runtime_mode", "auto")),
        "database": "PostgreSQL (source of truth) + ChromaDB (vector index)",
        "pipeline": [
            "ChromaDB semantic retrieval with nomic-embed-text",
            "Llama 3.1 8B relevance grading with CRAG retry loop",
            "Command-R7B synthesis with inline citations",
            "Deterministic clause map + regex issue detection (always runs)",
        ],
        "security": [
            "All models run locally via Ollama - no data leaves the machine.",
            "Uploaded documents remain in local PostgreSQL/filesystem.",
            "Graceful deterministic fallback when Ollama is unavailable.",
        ],
    }
    return base


def generate_agreement_v2(
    details: dict[str, str],
    runtime_mode: str | None = None,
) -> dict[str, Any]:
    effective_mode = resolve_runtime_mode(runtime_mode)
    draft = generate_agreement(details)
    query = " ".join(str(v) for v in details.values()) or "M&A agreement drafting template"
    corpus_results = retrieve_from_corpus(query, top_k=8, runtime_mode=effective_mode)
    draft["corpus_results"] = corpus_results
    draft["corpus_context_preview"] = build_context(corpus_results, limit=2200)
    draft["version"] = "V2 Corrective RAG - 2-model architecture"
    draft["runtime_mode"] = effective_mode
    return draft


def corpus_status() -> dict[str, Any]:
    return get_db().stats()


def ingest_deposited_documents() -> list[dict[str, Any]]:
    return get_db().ingest_deposit_dirs()
