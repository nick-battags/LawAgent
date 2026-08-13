"""Context-only facade for explicitly uploaded Supermemory Session sources.

The application does not enforce provider retention for Research-only sessions.
Hub deletion and sweep flows perform best-effort explicit cleanup.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from scripts.supermemory_adapter import (
    SupermemoryAdapter,
    SupermemoryAdapterError,
)

logger = logging.getLogger(__name__)

DEFAULT_SESSION_CONTEXT_MAX_CHARS = 4000

_PII_TOKENS = (
    "@",
    "ssn",
    "ein",
    "passport",
    "license",
    "iban",
    "routing",
    "account number",
    "credit card",
    "date of birth",
    "dob",
)
_PII_REGEX = re.compile(
    r"|".join(
        re.escape(token) if token == "@" else rf"\b{re.escape(token)}\b"
        for token in _PII_TOKENS
    ),
    re.IGNORECASE,
)


class SessionContextValidationError(ValueError):
    """The source payload failed an application-side safety check."""


def _context_max_chars() -> int:
    raw = os.environ.get(
        "SESSION_CONTEXT_MAX_CHARS",
        str(DEFAULT_SESSION_CONTEXT_MAX_CHARS),
    )
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        logger.warning("Session source limit invalid; using safe default")
        return DEFAULT_SESSION_CONTEXT_MAX_CHARS


class SessionMemory:
    """Session-scoped context operations over the Supermemory adapter."""

    def __init__(
        self,
        session_id: str,
        adapter: SupermemoryAdapter | None = None,
    ) -> None:
        self.session_id = session_id
        self.max_chars = _context_max_chars()
        self.adapter = adapter or SupermemoryAdapter()

    def _validate_context(self, content: str, metadata: dict[str, Any]) -> None:
        if metadata.get("anonymized") is not True:
            raise SessionContextValidationError(
                "Session source must be anonymized before upload"
            )
        if len(content) > self.max_chars:
            raise SessionContextValidationError(
                f"Session source exceeds the {self.max_chars}-character storage limit"
            )
        if _PII_REGEX.search(content):
            raise SessionContextValidationError(
                "Session source failed the post-anonymization PII check"
            )

        try:
            from scripts.pii_firewall import screen

            blocked, _reason = screen(content)
        except ImportError:
            blocked = False
        except Exception as exc:
            raise SessionContextValidationError(
                "Session source safety check is unavailable"
            ) from exc
        if blocked:
            raise SessionContextValidationError(
                "Session source failed the post-anonymization safety check"
            )

    def add_context(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        """Validate and add one context document."""
        context_metadata = {
            **metadata,
            "kind": "context",
        }
        self._validate_context(content, context_metadata)
        return self.adapter.add_context(
            self.session_id,
            content,
            context_metadata,
        )

    def list_context(self) -> list[dict[str, Any]]:
        return self.adapter.list_context(self.session_id)

    def recall_context(
        self,
        query: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        results = self.adapter.recall_context(self.session_id, query, limit=limit)
        return [
            result
            for result in results
            if isinstance(result.get("content"), str)
            and result["content"].strip()
        ]

    def delete_context(self, document_id: str) -> bool:
        return self.adapter.delete_context(self.session_id, document_id)

    def clear(self) -> bool:
        """Best-effort cleanup used by explicit Hub delete and sweep flows."""
        try:
            return self.adapter.clear_session(self.session_id)
        except SupermemoryAdapterError:
            return False


def get_session_memory(session_id: str) -> SessionMemory:
    """Return a context facade bound to one session ID."""
    return SessionMemory(session_id)
