"""Corrective RAG pipeline with 2-model architecture.

Flow: Retrieve (ChromaDB) → Grade (Llama 3.1) → Rewrite query if fail →
Retry (max 2) → Generate (Command-R7B with citations).
Falls back to deterministic keyword grading when Ollama is unavailable.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MAX_CRAG_RETRIES = 2
RETRIEVAL_TOP_K = 4
VALID_RUNTIME_MODES = {"auto", "llm", "deterministic"}


def _normalize_mode(mode: str | None) -> str | None:
    if not mode:
        return None
    normalized = mode.strip().lower()
    return normalized if normalized in VALID_RUNTIME_MODES else None


def _configured_mode() -> str:
    return _normalize_mode(os.environ.get("LAWAGENT_RUNTIME_MODE", "auto")) or "auto"


def _allow_mode_override() -> bool:
    value = os.environ.get("LAWAGENT_ALLOW_RUNTIME_MODE_OVERRIDE", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def resolve_runtime_mode(requested_mode: str | None = None) -> str:
    configured = _configured_mode()
    requested = _normalize_mode(requested_mode)
    if requested and _allow_mode_override():
        return requested
    return configured


def retrieve_and_grade(
    query: str,
    top_k: int = RETRIEVAL_TOP_K,
    category: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    from scripts.vector_store import get_vector_store
    from scripts.llm_provider import get_llm

    store = get_vector_store()
    llm = get_llm()
    runtime_mode = resolve_runtime_mode(mode)
    llm_available = llm.is_available()
    use_llm = runtime_mode != "deterministic" and llm_available

    candidates = store.query(query, top_k=top_k, category=category)

    if not candidates:
        from scripts.ma_corpus_db import get_db

        candidates = get_db().retrieve(query, top_k=top_k, category=category)

    if runtime_mode == "llm" and not llm_available:
        return {
            "relevant": [],
            "query_history": [query],
            "retries": 0,
            "grader": "llm-only (ollama unavailable)",
            "mode": runtime_mode,
            "total_candidates": len(candidates),
        }

    if not use_llm:
        return {
            "relevant": _keyword_grade(query, candidates),
            "query_history": [query],
            "retries": 0,
            "grader": "deterministic",
            "mode": runtime_mode,
            "total_candidates": len(candidates),
        }

    relevant: list[dict[str, Any]] = []
    irrelevant_snippets: list[str] = []
    for doc in candidates:
        result = llm.grade_document(query, doc.get("text", ""))
        if result.get("score") == "fallback":
            return {
                "relevant": _keyword_grade(query, candidates),
                "query_history": [query],
                "retries": 0,
                "grader": "deterministic (LLM connection lost)",
                "mode": "auto",
                "total_candidates": len(candidates),
            }
        if result.get("score") == "yes":
            doc["grade"] = "relevant"
            doc["grade_reason"] = "Approved by Llama 3.1 grader"
            relevant.append(doc)
        else:
            irrelevant_snippets.append(doc.get("text", "")[:200])

    query_history = [query]
    retries = 0
    while not relevant and retries < MAX_CRAG_RETRIES:
        failed_ctx = " | ".join(irrelevant_snippets[:3])
        rewritten = llm.rewrite_query(query, failed_ctx)
        query_history.append(rewritten)
        logger.info("CRAG retry %d: rewritten → '%s'", retries + 1, rewritten[:120])

        candidates = store.query(rewritten, top_k=top_k, category=category)
        if not candidates:
            from scripts.ma_corpus_db import get_db

            candidates = get_db().retrieve(rewritten, top_k=top_k, category=category)

        irrelevant_snippets = []
        for doc in candidates:
            result = llm.grade_document(query, doc.get("text", ""))
            if result.get("score") == "fallback":
                return {
                    "relevant": _keyword_grade(query, candidates),
                    "query_history": query_history,
                    "retries": retries,
                    "grader": "deterministic (LLM connection lost)",
                    "mode": "auto",
                    "total_candidates": len(candidates),
                }
            if result.get("score") == "yes":
                doc["grade"] = "relevant"
                doc["grade_reason"] = f"Approved after query rewrite (attempt {retries + 1})"
                relevant.append(doc)
            else:
                irrelevant_snippets.append(doc.get("text", "")[:200])
        retries += 1

    return {
        "relevant": relevant,
        "query_history": query_history,
        "retries": retries,
        "grader": f"llama3.1 ({llm.grader_model})",
        "mode": runtime_mode,
        "total_candidates": len(candidates),
    }


def generate_with_context(
    query: str,
    relevant_docs: list[dict[str, Any]],
    contract_text: str = "",
    mode: str | None = None,
) -> dict[str, Any]:
    from scripts.llm_provider import get_llm

    llm = get_llm()
    runtime_mode = resolve_runtime_mode(mode)
    llm_available = llm.is_available()

    if runtime_mode == "llm" and not llm_available:
        return {
            "analysis": "",
            "key_findings": [],
            "corrective_suggestions": [],
            "risk_level": "unknown",
            "citations": [],
            "generator": "llm-only (ollama unavailable)",
        }

    if runtime_mode == "deterministic" or not llm_available or not relevant_docs:
        return {
            "analysis": "",
            "key_findings": [],
            "corrective_suggestions": [],
            "risk_level": "unknown",
            "citations": [],
            "generator": "deterministic",
        }

    result = llm.generate_analysis(query, relevant_docs, contract_text)
    result["generator"] = f"command-r7b ({llm.generator_model})"
    return result


def enhance_issue_with_llm(
    issue_title: str,
    issue_description: str,
    corpus_excerpts: list[dict[str, Any]],
    mode: str | None = None,
) -> dict[str, Any]:
    from scripts.llm_provider import get_llm

    llm = get_llm()
    runtime_mode = resolve_runtime_mode(mode)
    if runtime_mode == "deterministic" or not llm.is_available() or not corpus_excerpts:
        return {}
    return llm.enhance_issue(issue_title, issue_description, corpus_excerpts)


def pipeline_status() -> dict[str, Any]:
    from scripts.vector_store import get_vector_store
    from scripts.llm_provider import get_llm

    store = get_vector_store()
    llm = get_llm()
    return {
        "vector_store": store.status(),
        "llm": llm.model_status(),
        "max_retries": MAX_CRAG_RETRIES,
        "retrieval_top_k": RETRIEVAL_TOP_K,
        "runtime_mode": _configured_mode(),
        "runtime_mode_override_enabled": _allow_mode_override(),
    }


def _keyword_grade(
    query: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    relevant: list[dict[str, Any]] = []
    query_terms = {t for t in query.lower().split() if len(t) > 3}
    for result in results:
        text = result.get("text", "").lower()
        overlap = sum(1 for t in query_terms if t in text)
        if overlap or result.get("score", 0) >= 2:
            graded = dict(result)
            graded["grade"] = "relevant"
            graded["grade_reason"] = (
                f"Keyword match: {overlap} terms (deterministic fallback)"
            )
            relevant.append(graded)
    return relevant
