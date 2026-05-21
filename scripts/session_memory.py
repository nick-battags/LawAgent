"""Per-session memory via Supermemory for the demo pipeline.

Each user session gets a container_tag = session_id. Writes are gated behind:
  1. Length limit (SESSION_MEMORY_MAX_SUMMARY_CHARS, default 2000)
  2. Naive PII heuristic (plain token list in summary)
  3. PII firewall re-screen before write (via scripts.pii_firewall if available)

Only anonymized content (metadata.anonymized=True) is ever written.

Env vars:
  SUPERMEMORY_API_KEY            — required
  SESSION_MEMORY_TTL_HOURS       — per-session forget-after (default 24)
  SESSION_MEMORY_MAX_SUMMARY_CHARS — max chars per summary write (default 2000)
  REVIEW_WRITES_ENABLED          — master toggle (default true)
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

# PII heuristic tokens. Word boundaries (\b) prevent false positives like
# "ein" matching "being/their/certain", "iban" matching "Caribbean", "dob"
# matching "doberman", "license" matching "licensee". "@" stays as substring
# match because @ isn't a word character (regex \b wouldn't bracket it).
_PII_TOKENS = (
    "@", "ssn", "ein", "passport", "license", "iban", "routing",
    "account number", "credit card", "date of birth", "dob",
)
_PII_REGEX = re.compile(
    r"|".join(
        # "@" stays as raw character match; everything else gets word boundaries
        re.escape(t) if t == "@" else rf"\b{re.escape(t)}\b"
        for t in _PII_TOKENS
    ),
    re.IGNORECASE,
)


class SessionMemory:
    """Supermemory-backed per-session context store.

    All writes enforce:
    - content length ≤ SESSION_MEMORY_MAX_SUMMARY_CHARS
    - no raw PII tokens in content
    - metadata.anonymized must be True
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.ttl_hours = int(os.environ.get("SESSION_MEMORY_TTL_HOURS", "24"))
        self.max_chars = int(os.environ.get("SESSION_MEMORY_MAX_SUMMARY_CHARS", "2000"))
        self._client: Any = None
        self._client_lock = threading.Lock()

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    api_key = os.environ.get("SUPERMEMORY_API_KEY", "")
                    if not api_key:
                        raise RuntimeError("SUPERMEMORY_API_KEY env var not set")
                    import supermemory
                    self._client = supermemory.Supermemory(api_key=api_key)
        return self._client

    def _writes_enabled(self) -> bool:
        return os.environ.get("REVIEW_WRITES_ENABLED", "true").lower() not in ("false", "0", "no")

    def _passes_length_guard(self, content: str) -> bool:
        if len(content) > self.max_chars:
            logger.warning(
                "SessionMemory write blocked for session %s: content length %d > max %d",
                self.session_id, len(content), self.max_chars,
            )
            return False
        return True

    def _passes_pii_heuristic(self, content: str) -> bool:
        # Word-boundary regex catches actual PII tokens without false positives
        # in common English words (e.g., "ein" used to match "being/their").
        match = _PII_REGEX.search(content)
        if match:
            logger.warning(
                "SessionMemory write blocked for session %s: PII token '%s' detected",
                self.session_id, match.group(0),
            )
            return False
        return True

    def _passes_firewall(self, content: str) -> bool:
        try:
            from scripts.pii_firewall import screen
            blocked, reason = screen(content)
            if blocked:
                logger.warning(
                    "SessionMemory write blocked by PII firewall for session %s: %s",
                    self.session_id, reason,
                )
                return False
        except ImportError:
            pass
        return True

    def _validate_write(self, content: str, metadata: dict[str, Any]) -> bool:
        if not metadata.get("anonymized"):
            logger.warning(
                "SessionMemory write blocked for session %s: metadata.anonymized is not True",
                self.session_id,
            )
            return False
        return (
            self._passes_length_guard(content)
            and self._passes_pii_heuristic(content)
            and self._passes_firewall(content)
        )

    def write_summary(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Write an anonymized session summary to Supermemory.

        Returns the memory ID on success, None on validation failure or write error.
        The user's download is never blocked even if this returns None.
        """
        if not self._writes_enabled():
            logger.info("SessionMemory write skipped: REVIEW_WRITES_ENABLED=false")
            return None

        meta = {
            "kind": "session_summary",
            "session_id": self.session_id,
            "schema_version": "v1",
            "anonymized": True,
            **(metadata or {}),
        }

        if not self._validate_write(content, meta):
            return None

        try:
            client = self._get_client()
            result = client.memories.add(
                content=content,
                container_tag=self.session_id,
                metadata=meta,
                forget_after=f"{self.ttl_hours}h",
            )
            memory_id = getattr(result, "id", None)
            logger.info(
                "SessionMemory: wrote summary for session %s (id=%s, chars=%d)",
                self.session_id, memory_id, len(content),
            )
            return memory_id
        except Exception as exc:
            logger.error(
                "SessionMemory write failed for session %s: %s — download not affected",
                self.session_id, exc,
            )
            return None

    def write(
        self,
        content: str,
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Write any anonymized memory record (context, chat_exchange, etc.).

        kind must be one of: context, chat_exchange, review_summary.
        """
        allowed_kinds = {"context", "chat_exchange", "review_summary", "session_summary"}
        if kind not in allowed_kinds:
            logger.warning("SessionMemory write blocked: unknown kind '%s'", kind)
            return None

        if not self._writes_enabled():
            return None

        meta = {
            "kind": kind,
            "session_id": self.session_id,
            "anonymized": True,
            **(metadata or {}),
        }

        if not self._validate_write(content, meta):
            return None

        try:
            client = self._get_client()
            result = client.memories.add(
                content=content,
                container_tag=self.session_id,
                metadata=meta,
                forget_after=f"{self.ttl_hours}h",
            )
            return getattr(result, "id", None)
        except Exception as exc:
            logger.error("SessionMemory write failed for session %s kind=%s: %s", self.session_id, kind, exc)
            return None

    def recall(
        self,
        query: str = "",
        kind: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve session memory records, optionally filtered by kind."""
        try:
            client = self._get_client()
            filters: dict[str, Any] = {"AND": []}
            if kind:
                filters["AND"].append({"key": "kind", "value": kind})

            kwargs: dict[str, Any] = {
                "container_tag": self.session_id,
                "limit": limit,
            }
            if query:
                kwargs["q"] = query
            if filters["AND"]:
                kwargs["filters"] = filters

            response = client.search.execute(**kwargs)
            return [
                {
                    "content": getattr(r, "content", ""),
                    "metadata": getattr(r, "metadata", {}),
                    "score": getattr(r, "score", 0.0),
                }
                for r in (response.results or [])
            ]
        except Exception as exc:
            logger.warning("SessionMemory recall failed for session %s: %s", self.session_id, exc)
            return []

    def clear(self) -> bool:
        """Delete all memory for this session. Used on explicit user delete."""
        try:
            client = self._get_client()
            client.containers.delete(container_tag=self.session_id)
            logger.info("SessionMemory: cleared container for session %s", self.session_id)
            return True
        except Exception as exc:
            logger.warning("SessionMemory clear failed for session %s: %s", self.session_id, exc)
            return False


def get_session_memory(session_id: str) -> SessionMemory:
    """Factory — returns a SessionMemory bound to the given session_id."""
    return SessionMemory(session_id)
