"""Context attachment handler for the Drafting & Review Hub.

POST /api/v2/context/attach
  Accepts .docx, .pdf, or pasted text. Anonymizes via Flash-Lite,
  embeds via Cohere Embed v4, and writes to Supermemory under the
  session_id container tag with metadata.kind="context".

Reused across drafting, review, and chat for the rest of the session.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MAX_BYTES = int(os.environ.get("HUB_MAX_BYTES", str(25 * 1024 * 1024)))


def attach_context(
    session_id: str,
    content: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Ingest a context attachment for a hub session.

    Accepts either pasted text (content) or a file (file_bytes + filename).
    Returns {"memory_id": str, "char_count": int, "status": "ok"|"error"}.
    """
    if file_bytes and len(file_bytes) > MAX_BYTES:
        return {"status": "error", "error": f"File exceeds {MAX_BYTES // (1024*1024)} MB limit"}

    # Extract text
    if file_bytes and filename:
        try:
            from scripts.hub_pipeline import extract_text
            raw_text = extract_text(file_bytes, filename)
        except Exception as exc:
            logger.warning("Context attachment extraction failed for session %s: %s", session_id, exc)
            return {"status": "error", "error": str(exc)}
    elif content:
        raw_text = content
    else:
        return {"status": "error", "error": "Provide either content text or a file"}

    if not raw_text.strip():
        return {"status": "error", "error": "Extracted text is empty"}

    # PII screen before processing
    from scripts.pii_firewall import screen
    blocked, reason = screen(raw_text[:2000])  # screen the first 2000 chars
    if blocked:
        logger.warning("Context attachment blocked by PII firewall for session %s: %s", session_id, reason)
        return {"status": "error", "error": f"Content blocked: {reason}"}

    # Anonymize
    from scripts.anonymizer import get_session_anonymizer
    anon = get_session_anonymizer(session_id)
    anon_text, _ = anon.anonymize(raw_text)

    # Write to Supermemory
    source_label = filename or "pasted text"
    memory_content = f"[Context: {source_label}]\n{anon_text}"
    if len(memory_content) > 4000:
        memory_content = memory_content[:3997] + "..."

    from scripts.session_memory import get_session_memory
    mem = get_session_memory(session_id)
    memory_id = mem.write(
        content=memory_content,
        kind="context",
        metadata={
            "anonymized": True,
            "source": source_label,
            "char_count": len(anon_text),
        },
    )

    if memory_id:
        logger.info(
            "Context attached for session %s: %d chars from %s (id=%s)",
            session_id, len(anon_text), source_label, memory_id,
        )
        return {"status": "ok", "memory_id": memory_id, "char_count": len(anon_text)}
    else:
        logger.warning("Context write failed or was blocked for session %s", session_id)
        return {"status": "ok", "memory_id": None, "char_count": len(anon_text),
                "note": "Attachment processed but not persisted to session memory"}
