"""Anchored chat for the Drafting & Review Hub.

POST /api/v2/hub/<session_id>/ask
  body: {"clause_anchor": "§ 7.4", "question": "..."}

Pipeline:
  1. Pseudonymize question through session anonymizer
  2. Retrieve from corpus (filtered by clause_anchor + category as hints)
  3. Retrieve context attachments from Supermemory (kind=context)
  4. Call Gemini 2.5 Flash with clause + context + corpus top-k
  5. Re-hydrate placeholders before streaming back
  6. Write chat exchange to Supermemory with metadata.kind=chat_exchange

Returns a generator of streamed text chunks (for Flask SSE).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Generator

logger = logging.getLogger(__name__)


def ask_clause(
    session_id: str,
    clause_anchor: str,
    question: str,
    clause_text: str = "",
    category: str | None = None,
) -> Generator[str, None, None]:
    """Stream an answer for an anchored clause question.

    Yields plain text chunks. Caller wraps in SSE.
    """
    from scripts.anonymizer import get_session_anonymizer
    from scripts.llm_provider import get_llm, VertexProvider

    anon = get_session_anonymizer(session_id)
    provider = get_llm()

    # Pseudonymize the question
    anon_question, _ = anon.anonymize(question)

    # Retrieve corpus chunks (use clause anchor + category as hints)
    corpus_query = f"{clause_anchor} {anon_question}"
    corpus_chunks = _retrieve_for_chat(corpus_query, category=category, top_k=6)

    # Retrieve session context attachments from Supermemory
    context_chunks = _get_context_attachments(session_id, anon_question)

    # Build prompt
    clause_section = f"\nCLAUSE ({clause_anchor}):\n{clause_text}\n" if clause_text else ""
    corpus_text = _format_chunks(corpus_chunks, "CORPUS EXCERPT")
    context_text = _format_chunks(context_chunks, "SESSION CONTEXT")

    prompt = (
        "You are an expert M&A legal analyst answering a question about a specific contract clause.\n\n"
        f"{clause_section}"
        f"QUESTION: {anon_question}\n\n"
        f"{corpus_text}\n\n"
        f"{context_text}\n\n"
        "Answer the question precisely. Cite corpus excerpts where applicable. "
        "Keep the answer under 400 words."
    )

    if not isinstance(provider, VertexProvider):
        answer = "[Chat requires LLM_PROVIDER=vertex]"
        yield anon.rehydrate(answer)
        return

    try:
        raw_answer = provider._generate(prompt, model=provider.generator_model, temperature=0.2)
        rehydrated = anon.rehydrate(raw_answer)

        _write_chat_exchange(session_id, clause_anchor, anon_question, raw_answer)

        # Stream word by word (simple chunking for SSE demo)
        words = rehydrated.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")

    except Exception as exc:
        logger.error("Hub chat failed for session %s clause %s: %s", session_id, clause_anchor, exc)
        yield f"[Error generating answer: {exc}]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _retrieve_for_chat(
    query: str,
    category: str | None = None,
    top_k: int = 6,
) -> list[dict[str, Any]]:
    try:
        from scripts.vector_store import get_demo_vector_store
        store = get_demo_vector_store()
        return store.query(query, top_k=top_k, category=category)
    except Exception as exc:
        logger.warning("Chat retrieval failed: %s", exc)
        return []


def _get_context_attachments(session_id: str, query: str) -> list[dict[str, Any]]:
    """Retrieve session context attachments from Supermemory."""
    try:
        from scripts.session_memory import get_session_memory
        mem = get_session_memory(session_id)
        results = mem.recall(query=query, kind="context", limit=4)
        return [{"text": r["content"], "title": "Session context", "page": ""} for r in results]
    except Exception as exc:
        logger.warning("Context attachment retrieval failed for session %s: %s", session_id, exc)
        return []


def _write_chat_exchange(
    session_id: str,
    clause_anchor: str,
    anon_question: str,
    anon_answer: str,
) -> None:
    content = f"Q ({clause_anchor}): {anon_question}\nA: {anon_answer}"
    if len(content) > 2000:
        content = content[:1997] + "..."
    try:
        from scripts.session_memory import get_session_memory
        mem = get_session_memory(session_id)
        mem.write(
            content=content,
            kind="chat_exchange",
            metadata={
                "anonymized": True,
                "clause_anchor": clause_anchor,
            },
        )
    except Exception as exc:
        logger.warning("Chat exchange write failed for session %s: %s", session_id, exc)


def _format_chunks(chunks: list[dict[str, Any]], label: str) -> str:
    parts = []
    for i, c in enumerate(chunks[:5], 1):
        source = f"[{c.get('title', 'Unknown')}]"
        parts.append(f"{label} {i} {source}:\n{c.get('text', '')[:600]}")
    return "\n\n".join(parts)
