"""Validate, extract, anonymize, and attach one Session source."""

from __future__ import annotations

import logging
import os
from typing import Any

from scripts.session_memory import (
    DEFAULT_SESSION_CONTEXT_MAX_CHARS,
    SessionContextValidationError,
    get_session_memory,
)
from scripts.supermemory_adapter import (
    SupermemoryRejectedError,
    SupermemoryUnavailableError,
)

logger = logging.getLogger(__name__)

MAX_BYTES = int(os.environ.get("HUB_MAX_BYTES", str(25 * 1024 * 1024)))


def _validation_error(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error_code": "invalid_source",
        "error": message,
    }


def _provider_error(
    code: str,
    message: str,
    processing_status: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "error",
        "error_code": code,
        "error": message,
    }
    if processing_status:
        result["processing_status"] = processing_status
    return result


def _prepare_context_payload(
    source_label: str,
    anonymized_text: str,
    max_chars: int,
) -> tuple[str, int, bool]:
    prefix = f"[Context: {source_label}]\n"
    available = max_chars - len(prefix)
    if available <= 0:
        raise SessionContextValidationError("Session source name is too long")
    truncated = len(anonymized_text) > available
    if truncated:
        body = (
            anonymized_text[: max(0, available - 3)] + "..."
            if available >= 3
            else anonymized_text[:available]
        )
    else:
        body = anonymized_text
    return prefix + body, len(body), truncated


def attach_context(
    session_id: str,
    content: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Attach pasted text or an extracted PDF/DOCX to one session."""
    if file_bytes and len(file_bytes) > MAX_BYTES:
        return _validation_error(
            f"File exceeds {MAX_BYTES // (1024 * 1024)} MB limit"
        )

    if file_bytes and filename:
        try:
            from scripts.hub_pipeline import extract_text

            raw_text = extract_text(file_bytes, filename)
        except Exception:
            logger.warning("Session source extraction failed")
            return _validation_error(
                "The source could not be extracted. Use a valid PDF or DOCX file."
            )
    elif content:
        raw_text = content
    else:
        return _validation_error("Provide either content text or a file")

    if not raw_text.strip():
        return _validation_error("Extracted text is empty")

    from scripts.pii_firewall import screen

    blocked, _reason = screen(raw_text[:2000])
    if blocked:
        logger.warning("Session source blocked by pre-processing safety check")
        return _validation_error(
            "Use public or fictional material without identifying information."
        )

    from scripts.anonymizer import get_session_anonymizer

    anonymizer = get_session_anonymizer(session_id)
    anonymized_text, _anonymizer_map = anonymizer.anonymize(raw_text)

    source_label = filename or "pasted text"
    memory = get_session_memory(session_id)
    try:
        memory_content, stored_char_count, truncated = _prepare_context_payload(
            source_label,
            anonymized_text,
            memory.max_chars or DEFAULT_SESSION_CONTEXT_MAX_CHARS,
        )
        accepted = memory.add_context(
            content=memory_content,
            metadata={
                "anonymized": True,
                "source": source_label,
                "char_count": stored_char_count,
                "truncated": truncated,
            },
        )
    except SessionContextValidationError as exc:
        return _validation_error(str(exc))
    except SupermemoryRejectedError:
        return _provider_error(
            "provider_rejected",
            "The Session source provider rejected the upload.",
        )
    except SupermemoryUnavailableError:
        return _provider_error(
            "provider_unavailable",
            "Session sources are temporarily unavailable. Try again shortly.",
        )

    document_id = str(accepted.get("id") or "").strip()
    processing_status = str(
        accepted.get("processing_status") or "processing"
    )
    if not document_id:
        return _provider_error(
            "provider_rejected",
            "The Session source provider did not accept the upload.",
        )
    if processing_status == "failed":
        return _provider_error(
            "provider_rejected",
            "The Session source provider could not process the upload.",
            processing_status="failed",
        )

    return {
        "status": "ok",
        "id": document_id,
        "memory_id": document_id,
        "char_count": stored_char_count,
        "processing_status": processing_status,
        "truncated": truncated,
    }
