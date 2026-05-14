"""Drafting & Review Hub pipeline (Phase 2c).

Three modes — all converge on a common issue-spotter + missing-clause proposer:
  Mode A: generate  — Gemini drafts a contract from a prompt
  Mode B: revise    — Gemini revises an uploaded draft per a prompt
  Mode C: review    — Gemini reviews an uploaded draft (no prompt required)

All modes:
  1. Extract text from uploaded .docx/.pdf (modes B/C) or use prompt (A)
  2. Anonymize via Flash-Lite through the session anonymizer
  3. Embed via Cohere Embed v4 → retrieve from Neon pgvector → Rerank 3.5
  4. Call issue-spotter (≤HUB_MAX_CHANGES changes, structured JSON)
  5. Call missing-clause proposer (≤HUB_MAX_MISSING records)
  6. Persist hub_sessions + hub_changes to Postgres
  7. Return session_id for client polling

Env vars (all have defaults; see 02c_Editing_Hub.md §Env vars):
  HUB_ENABLED, HUB_GENERATE_ENABLED, HUB_REVISE_ENABLED, HUB_REVIEW_ENABLED
  HUB_MAX_CHANGES=14, HUB_MAX_MISSING=5
  HUB_TTL_MINUTES=1440, HUB_IDLE_TTL_MINUTES=120
  HUB_MAX_BYTES=26214400
  GRADER_LLM_ENABLED=false, GRADER_LLM_BAND_HIGH=0.72, GRADER_LLM_BAND_LOW=0.45
"""

from __future__ import annotations

import io
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env var helpers
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool = True) -> bool:
    return os.environ.get(name, "true" if default else "false").lower() not in ("false", "0", "no")

def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))

def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


VALID_CATEGORIES = frozenset({
    "assignment", "indemnification", "confidentiality", "non_solicit",
    "mac_definition", "reps_warranties", "governing_law", "dispute_resolution",
    "termination", "ip_ownership", "payment_terms", "liability_cap",
})

VALID_POSTURES = frozenset({"buy", "sell", "neutral"})
VALID_MODES = frozenset({"generate", "revise", "review"})


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from .docx or .pdf bytes."""
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return _extract_pdf(file_bytes)
    if name_lower.endswith(".docx"):
        return _extract_docx(file_bytes)
    raise ValueError(f"Unsupported file type: {filename}")


def _extract_pdf(file_bytes: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)
    return "\n\n".join(parts)


def _extract_docx(file_bytes: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def _retrieve_and_rerank(
    query: str,
    top_k: int = 12,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Embed → retrieve from demo store → Cohere Rerank 3.5 → return top results."""
    from scripts.vector_store import get_demo_vector_store
    from scripts.llm_provider import get_llm, VertexProvider

    store = get_demo_vector_store()
    provider = get_llm()

    # Retrieve candidates
    if isinstance(provider, VertexProvider):
        try:
            # Use Cohere embeddings for retrieval if backend supports it
            candidates = store.query(query, top_k=top_k * 2, category=category)
            if not candidates:
                return []
            # Rerank
            texts = [c["text"] for c in candidates]
            ranked = provider.rerank(query, texts, top_n=top_k)
            high = _env_float("GRADER_LLM_BAND_HIGH", 0.72)
            low = _env_float("GRADER_LLM_BAND_LOW", 0.45)
            result = []
            for r in ranked:
                score = r["relevance_score"]
                if score >= low:
                    doc = dict(candidates[r["index"]])
                    doc["rerank_score"] = score
                    result.append(doc)
            return result[:top_k]
        except Exception as exc:
            logger.warning("Rerank failed, using raw retrieval: %s", exc)

    # Fallback: raw vector retrieval
    return store.query(query, top_k=top_k, category=category)


# ---------------------------------------------------------------------------
# Issue spotter
# ---------------------------------------------------------------------------

def _run_issue_spotter(
    draft_text: str,
    posture: str,
    corpus_chunks: list[dict[str, Any]],
    context_chunks: list[dict[str, Any]],
    max_changes: int,
) -> list[dict[str, Any]]:
    """Call Gemini Flash to spot issues. Returns list of change dicts."""
    from scripts.llm_provider import get_llm, VertexProvider

    provider = get_llm()
    if not isinstance(provider, VertexProvider):
        logger.warning("Issue spotter requires VertexProvider; skipping")
        return []

    corpus_text = _format_corpus(corpus_chunks)
    context_text = _format_corpus(context_chunks, label="CONTEXT ATTACHMENT")

    prompt = (
        f"You are an expert M&A legal analyst reviewing a contract draft from a {posture}-side perspective.\n\n"
        f"DRAFT:\n{draft_text[:8000]}\n\n"
        f"CORPUS EXCERPTS:\n{corpus_text}\n\n"
        f"{context_text}\n\n"
        f"Identify up to {max_changes} issues in the draft. For each issue output a JSON object in this array:\n"
        '[\n'
        '  {\n'
        '    "clause_anchor": "§ 7.4",\n'
        '    "category": "<one of: ' + ", ".join(sorted(VALID_CATEGORIES)) + '>",\n'
        '    "severity": "high|med|low",\n'
        '    "kind": "redline",\n'
        '    "original_text": "exact text span being changed",\n'
        '    "proposed_text": "replacement text",\n'
        '    "rationale": "Why this matters for a ' + posture + '-side party",\n'
        '    "source_ref": "optional: playbook section or clause"\n'
        '  }\n'
        ']\n\n'
        "Output ONLY the JSON array, no explanation."
    )

    try:
        raw = provider._generate_json(prompt, model=provider.generator_model, temperature=0.1)
        changes = json.loads(raw)
        if not isinstance(changes, list):
            return []
        return [_normalize_change(c) for c in changes[:max_changes] if _valid_change(c)]
    except Exception as exc:
        logger.error("Issue spotter failed: %s", exc)
        return []


def _run_missing_clause_proposer(
    draft_text: str,
    posture: str,
    doc_type: str,
    existing_categories: set[str],
    max_missing: int,
) -> list[dict[str, Any]]:
    """Call Gemini Flash to propose missing clauses."""
    from scripts.llm_provider import get_llm, VertexProvider

    provider = get_llm()
    if not isinstance(provider, VertexProvider):
        return []

    covered = ", ".join(sorted(existing_categories)) if existing_categories else "none identified"
    prompt = (
        f"You are an expert M&A legal analyst reviewing a {posture}-side {doc_type}.\n\n"
        f"DRAFT (first 6000 chars):\n{draft_text[:6000]}\n\n"
        f"Categories already covered in the draft: {covered}\n\n"
        f"What clauses would a typical {posture}-side {doc_type} contain that this draft does NOT?\n"
        f"Return up to {max_missing} missing clauses as a JSON array:\n"
        '[\n'
        '  {\n'
        '    "clause_anchor": null,\n'
        '    "category": "<category from vocabulary>",\n'
        '    "severity": "high|med|low",\n'
        '    "kind": "missing_clause",\n'
        '    "original_text": null,\n'
        '    "proposed_text": "Complete drop-in clause language",\n'
        '    "rationale": "Why a ' + posture + '-side party needs this clause",\n'
        '    "source_ref": null\n'
        '  }\n'
        ']\n\n'
        "Output ONLY the JSON array."
    )

    try:
        raw = provider._generate_json(prompt, model=provider.generator_model, temperature=0.15)
        changes = json.loads(raw)
        if not isinstance(changes, list):
            return []
        result = []
        for c in changes[:max_missing]:
            c["kind"] = "missing_clause"
            c["original_text"] = None
            result.append(_normalize_change(c))
        return result
    except Exception as exc:
        logger.error("Missing-clause proposer failed: %s", exc)
        return []


def _format_corpus(chunks: list[dict[str, Any]], label: str = "CORPUS EXCERPT") -> str:
    parts = []
    for i, c in enumerate(chunks[:8], 1):
        source = f"[{c.get('title', 'Unknown')}, p.{c.get('page', '?')}]"
        parts.append(f"{label} {i} {source}:\n{c.get('text', '')[:800]}")
    return "\n\n".join(parts)


def _valid_change(c: Any) -> bool:
    if not isinstance(c, dict):
        return False
    if not c.get("proposed_text"):
        return False
    if c.get("category") not in VALID_CATEGORIES:
        return False
    return True


def _normalize_change(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "clause_anchor": c.get("clause_anchor") or "",
        "category": c.get("category", "indemnification"),
        "severity": c.get("severity", "med") if c.get("severity") in ("high", "med", "low") else "med",
        "kind": c.get("kind", "redline"),
        "original_text": c.get("original_text"),
        "proposed_text": c.get("proposed_text", ""),
        "rationale": c.get("rationale", ""),
        "source_ref": c.get("source_ref") or "",
        "current_action": "pending",
        "current_text": c.get("proposed_text", ""),
    }


# ---------------------------------------------------------------------------
# Draft generator (Mode A)
# ---------------------------------------------------------------------------

def _generate_draft(
    prompt: str,
    posture: str,
    doc_type: str,
    governing_law: str,
    length_target: str,
    corpus_chunks: list[dict[str, Any]],
    context_chunks: list[dict[str, Any]],
) -> str:
    from scripts.llm_provider import get_llm, VertexProvider

    provider = get_llm()
    if not isinstance(provider, VertexProvider):
        raise RuntimeError("Draft generation requires VertexProvider (LLM_PROVIDER=vertex)")

    corpus_text = _format_corpus(corpus_chunks)
    context_text = _format_corpus(context_chunks, label="CONTEXT ATTACHMENT")

    gen_prompt = (
        f"You are an expert M&A lawyer drafting a {posture}-side {doc_type}.\n\n"
        f"INSTRUCTIONS:\n{prompt}\n\n"
        f"Governing law: {governing_law or 'Delaware'}\n"
        f"Target length: {length_target or 'standard (8-12 pages)'}\n\n"
        f"CORPUS PRECEDENTS:\n{corpus_text}\n\n"
        f"{context_text}\n\n"
        "Draft the complete contract. Use standard section numbering (§ 1, § 2, ...). "
        "Be precise. Include all standard provisions for this document type. "
        "Output ONLY the contract text, no explanations."
    )

    return provider._generate(gen_prompt, model=provider.generator_model, temperature=0.3)


# ---------------------------------------------------------------------------
# Draft reviser (Mode B)
# ---------------------------------------------------------------------------

def _revise_draft(
    original_text: str,
    prompt: str,
    posture: str,
    corpus_chunks: list[dict[str, Any]],
    context_chunks: list[dict[str, Any]],
) -> str:
    from scripts.llm_provider import get_llm, VertexProvider

    provider = get_llm()
    if not isinstance(provider, VertexProvider):
        raise RuntimeError("Draft revision requires VertexProvider (LLM_PROVIDER=vertex)")

    corpus_text = _format_corpus(corpus_chunks)
    context_text = _format_corpus(context_chunks, label="CONTEXT ATTACHMENT")

    rev_prompt = (
        f"You are an expert M&A lawyer revising a contract draft from a {posture}-side perspective.\n\n"
        f"REVISION INSTRUCTIONS:\n{prompt}\n\n"
        f"ORIGINAL DRAFT:\n{original_text[:8000]}\n\n"
        f"CORPUS PRECEDENTS:\n{corpus_text}\n\n"
        f"{context_text}\n\n"
        "Produce the revised contract. Preserve section numbering. Output ONLY the revised contract text."
    )

    return provider._generate(rev_prompt, model=provider.generator_model, temperature=0.2)


# ---------------------------------------------------------------------------
# Postgres persistence
# ---------------------------------------------------------------------------

def _persist_session(
    session_id: str,
    mode: str,
    posture: str,
    prompt: str | None,
    gcs_prefix: str,
    ttl_minutes: int,
    database_url: str,
) -> None:
    import psycopg
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hub_sessions
                    (id, mode, posture, prompt, expires_at, status, gcs_prefix)
                VALUES (%s, %s, %s, %s, %s, 'running', %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (session_id, mode, posture, prompt, expires_at, gcs_prefix),
            )
        conn.commit()


def _persist_changes(
    session_id: str,
    changes: list[dict[str, Any]],
    database_url: str,
) -> list[str]:
    """Insert hub_changes rows and return their UUIDs."""
    if not changes:
        return []
    import psycopg
    change_ids: list[str] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for c in changes:
                change_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO hub_changes
                        (id, session_id, clause_anchor, category, severity, kind,
                         original_text, proposed_text, rationale, source_ref,
                         current_action, current_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                    """,
                    (
                        change_id,
                        session_id,
                        c.get("clause_anchor") or "",
                        c["category"],
                        c.get("severity", "med"),
                        c.get("kind", "redline"),
                        c.get("original_text"),
                        c["proposed_text"],
                        c.get("rationale", ""),
                        c.get("source_ref") or "",
                        c["current_text"],
                    ),
                )
                change_ids.append(change_id)
        conn.commit()
    return change_ids


def _update_session_status(session_id: str, status: str, database_url: str) -> None:
    import psycopg
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hub_sessions SET status = %s WHERE id = %s",
                (status, session_id),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run_hub_session(
    mode: str,
    posture: str,
    prompt: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    doc_type: str = "NDA",
    governing_law: str = "Delaware",
    length_target: str = "",
    context_chunks: list[dict[str, Any]] | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Run a full hub session synchronously. Returns session result dict.

    In production this would run in a background task; kept synchronous here
    so it can be called from a Cloud Run Job or a threading.Thread in Flask.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode!r}. Must be one of {VALID_MODES}")
    if posture not in VALID_POSTURES:
        raise ValueError(f"Invalid posture: {posture!r}. Must be one of {VALID_POSTURES}")

    max_changes = _env_int("HUB_MAX_CHANGES", 14)
    max_missing = _env_int("HUB_MAX_MISSING", 5)
    ttl_minutes = _env_int("HUB_TTL_MINUTES", 1440)
    db_url = database_url or os.environ.get("DATABASE_URL", "")

    session_id = str(uuid.uuid4())
    gcs_prefix = f"review-staging/{session_id}/"

    if db_url:
        _persist_session(session_id, mode, posture, prompt, gcs_prefix, ttl_minutes, db_url)

    try:
        # ── Step 1: extract/obtain draft text ──────────────────────────────
        if mode == "generate":
            if not prompt:
                raise ValueError("Mode A (generate) requires a prompt")
            draft_text_raw = ""
        else:
            if not file_bytes or not filename:
                raise ValueError(f"Mode {mode} requires an uploaded file")
            draft_text_raw = extract_text(file_bytes, filename)

        # ── Step 2: anonymize ──────────────────────────────────────────────
        from scripts.anonymizer import get_session_anonymizer
        anon = get_session_anonymizer(session_id)
        draft_anon, _ = anon.anonymize(draft_text_raw) if draft_text_raw else ("", {})
        prompt_anon, _ = anon.anonymize(prompt) if prompt else ("", {})

        # ── Step 3: retrieve & rerank ──────────────────────────────────────
        query = prompt_anon or draft_anon[:500]
        corpus_chunks = _retrieve_and_rerank(query, top_k=12)
        ctx_chunks = context_chunks or []

        # ── Step 4: generate/revise draft (modes A and B) ─────────────────
        if mode == "generate":
            draft_anon = _generate_draft(
                prompt_anon, posture, doc_type, governing_law, length_target,
                corpus_chunks, ctx_chunks,
            )
        elif mode == "revise":
            draft_anon = _revise_draft(draft_anon, prompt_anon, posture, corpus_chunks, ctx_chunks)

        # ── Step 5: issue spotter ─────────────────────────────────────────
        redline_changes = _run_issue_spotter(
            draft_anon, posture, corpus_chunks, ctx_chunks, max_changes,
        )

        # ── Step 6: missing-clause proposer ───────────────────────────────
        covered_cats = {c["category"] for c in redline_changes}
        missing_changes = _run_missing_clause_proposer(
            draft_anon, posture, doc_type, covered_cats, max_missing,
        )

        all_changes = redline_changes + missing_changes

        # ── Step 7: persist to Postgres ────────────────────────────────────
        change_ids: list[str] = []
        if db_url:
            change_ids = _persist_changes(session_id, all_changes, db_url)
            _update_session_status(session_id, "ready", db_url)

        logger.info(
            "Hub session %s (%s/%s) complete: %d redlines, %d missing clauses",
            session_id, mode, posture, len(redline_changes), len(missing_changes),
        )

        return {
            "session_id": session_id,
            "status": "ready",
            "mode": mode,
            "posture": posture,
            "draft_text": draft_anon,
            "changes": all_changes,
            "change_ids": change_ids,
            "gcs_prefix": gcs_prefix,
        }

    except Exception as exc:
        logger.exception("Hub session %s failed: %s", session_id, exc)
        if db_url:
            try:
                _update_session_status(session_id, "failed", db_url)
            except Exception:
                pass
        raise
