"""Per-session Flash-Lite anonymizer for the Drafting & Review Hub.

Maintains a two-way pseudonym map for each session (24h in-memory TTL).
The map is NEVER written to Postgres or Supermemory — it lives only in
process memory and is discarded when the session expires or the process restarts.

Usage:
    anon = get_session_anonymizer(session_id)
    anon_text, _ = anon.anonymize(original_text)
    # ... pipeline uses anon_text only ...
    display_text = anon.rehydrate(anon_text)

Env vars:
  ANONYMIZER_PROVIDER  — "vertex_flash_lite" (default) or "regex_only"
  ANONYMIZER_TTL_HOURS — in-memory TTL for session maps (default 24)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_sessions: dict[str, "_SessionAnonymizer"] = {}
_sessions_lock = threading.Lock()


def get_session_anonymizer(session_id: str) -> "_SessionAnonymizer":
    """Return (creating if needed) the anonymizer bound to session_id."""
    ttl_hours = int(os.environ.get("ANONYMIZER_TTL_HOURS", "24"))
    with _sessions_lock:
        _evict_expired()
        if session_id not in _sessions:
            _sessions[session_id] = _SessionAnonymizer(session_id, ttl_hours)
        return _sessions[session_id]


def _evict_expired() -> None:
    now = time.time()
    expired = [sid for sid, anon in _sessions.items() if anon.expires_at <= now]
    for sid in expired:
        del _sessions[sid]
        logger.info("Anonymizer: evicted expired session %s", sid)


class _SessionAnonymizer:
    """In-memory pseudonym map for one hub session.

    placeholder → original  (forward map, used for rehydration)
    original_lower → placeholder  (reverse index, used to detect seen entities)
    """

    def __init__(self, session_id: str, ttl_hours: int) -> None:
        self.session_id = session_id
        self.expires_at = time.time() + ttl_hours * 3600
        self._map: dict[str, str] = {}         # placeholder → original
        self._reverse: dict[str, str] = {}     # original_lower → placeholder
        self._lock = threading.RLock()
        self._provider = os.environ.get("ANONYMIZER_PROVIDER", "vertex_flash_lite")

    def anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        """Anonymize text. Returns (anonymized_text, current_map_snapshot).

        Uses Flash-Lite when ANONYMIZER_PROVIDER=vertex_flash_lite and the
        LLM provider is VertexProvider; falls back to returning text unchanged
        if Flash-Lite is unavailable (pipeline must gate on this).
        """
        if not text:
            return text, self._snapshot()

        if self._provider == "vertex_flash_lite":
            try:
                return self._anonymize_via_llm(text)
            except Exception as exc:
                logger.warning(
                    "Anonymizer Flash-Lite failed for session %s: %s — using pass-through",
                    self.session_id, exc,
                )
                return text, self._snapshot()
        else:
            return text, self._snapshot()

    def rehydrate(self, anonymized_text: str) -> str:
        """Reverse all placeholders in anonymized_text back to originals."""
        with self._lock:
            result = anonymized_text
            for placeholder, original in self._map.items():
                result = result.replace(placeholder, original)
            return result

    def snapshot(self) -> dict[str, str]:
        return self._snapshot()

    def _snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._map)

    def _anonymize_via_llm(self, text: str) -> tuple[str, dict[str, str]]:
        from scripts.llm_provider import get_llm, VertexProvider
        provider = get_llm()
        if not isinstance(provider, VertexProvider):
            return text, self._snapshot()

        with self._lock:
            existing_map = dict(self._map)

        anon_text, updated_map = provider.anonymize(text, existing_map)

        with self._lock:
            self._map.update(updated_map)
            self._reverse = {v.lower(): k for k, v in self._map.items()}

        return anon_text, dict(self._map)
