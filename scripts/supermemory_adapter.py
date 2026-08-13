"""Narrow Supermemory adapter for explicitly uploaded Session sources.

This is the only application module that understands Supermemory SDK object
shapes. The shared Argus corpus remains outside Supermemory.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 0
_LIST_PAGE_SIZE = 100
_MAX_LIST_PAGES = 10


class SupermemoryAdapterError(RuntimeError):
    """Stable internal error that does not expose provider exception text."""

    code = "supermemory_error"


class SupermemoryUnavailableError(SupermemoryAdapterError):
    """The provider client or operation was unavailable."""

    code = "supermemory_unavailable"


class SupermemoryRejectedError(SupermemoryAdapterError):
    """The provider rejected or failed to identify an uploaded source."""

    code = "supermemory_rejected"


def _read_timeout() -> float:
    raw = os.environ.get("SUPERMEMORY_TIMEOUT_SECONDS", "")
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_SECONDS
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        logger.warning("supermemory operation=config outcome=default_timeout elapsed_ms=0")
        return DEFAULT_TIMEOUT_SECONDS


def _read_max_retries() -> int:
    raw = os.environ.get("SUPERMEMORY_MAX_RETRIES", "")
    try:
        value = int(raw) if raw else DEFAULT_MAX_RETRIES
        if value < 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        logger.warning("supermemory operation=config outcome=default_retries elapsed_ms=0")
        return DEFAULT_MAX_RETRIES


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _metadata(value: Any) -> dict[str, Any]:
    metadata = _field(value, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def normalize_processing_status(status: Any) -> str:
    """Map Supermemory workflow states to the public three-state contract."""
    normalized = str(status or "unknown").strip().lower()
    if normalized == "done":
        return "ready"
    if normalized == "failed":
        return "failed"
    return "processing"


class SupermemoryAdapter:
    """SDK boundary for Session-source add/list/recall/delete/clear."""

    def __init__(
        self,
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory or self._build_client
        self._client_lock = threading.Lock()
        self.timeout_seconds = _read_timeout()
        self.max_retries = _read_max_retries()

    def _build_client(self) -> Any:
        api_key = os.environ.get("SUPERMEMORY_API_KEY", "")
        if not api_key:
            raise RuntimeError("Supermemory API key is not configured")
        import supermemory

        return supermemory.Supermemory(
            api_key=api_key,
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._client_factory()
        return self._client

    @staticmethod
    def _log(operation: str, outcome: str, started_at: float) -> None:
        elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        logger.info(
            "supermemory operation=%s outcome=%s elapsed_ms=%d",
            operation,
            outcome,
            elapsed_ms,
        )

    def _run(self, operation: str, callback: Callable[[Any], Any]) -> Any:
        started_at = time.perf_counter()
        try:
            result = callback(self._get_client())
        except SupermemoryAdapterError as exc:
            self._log(operation, exc.code, started_at)
            raise
        except Exception as exc:
            self._log(operation, "unavailable", started_at)
            raise SupermemoryUnavailableError(
                "Session source service is temporarily unavailable"
            ) from exc
        self._log(operation, "ok", started_at)
        return result

    def add_context(
        self,
        session_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        """Add one anonymized Session source."""

        def operation(client: Any) -> dict[str, str]:
            response = client.add(
                content=content,
                container_tag=session_id,
                metadata={**metadata, "kind": "context"},
            )
            document_id = str(_field(response, "id", "") or "").strip()
            if not document_id:
                raise SupermemoryRejectedError(
                    "Session source provider returned no document ID"
                )
            return {
                "id": document_id,
                "processing_status": normalize_processing_status(
                    _field(response, "status", "unknown")
                ),
            }

        return self._run("add_context", operation)

    def list_context(self, session_id: str) -> list[dict[str, Any]]:
        """Enumerate all Session sources, including processing and failed ones."""

        def operation(client: Any) -> list[dict[str, Any]]:
            sources: list[dict[str, Any]] = []
            seen: set[str] = set()
            page = 1

            while page <= _MAX_LIST_PAGES:
                response = client.documents.list(
                    container_tags=[session_id],
                    limit=_LIST_PAGE_SIZE,
                    page=page,
                )
                documents = _field(response, "memories", []) or []
                for document in documents:
                    metadata = _metadata(document)
                    if metadata.get("kind") != "context":
                        continue
                    document_id = str(_field(document, "id", "") or "").strip()
                    if not document_id or document_id in seen:
                        continue
                    seen.add(document_id)
                    try:
                        char_count = max(0, int(metadata.get("char_count") or 0))
                    except (TypeError, ValueError):
                        char_count = 0
                    sources.append(
                        {
                            "id": document_id,
                            "filename": str(
                                metadata.get("source")
                                or metadata.get("title")
                                or _field(document, "title", "")
                                or "Untitled"
                            ),
                            "char_count": char_count,
                            "processing_status": normalize_processing_status(
                                _field(document, "status", "unknown")
                            ),
                        }
                    )

                pagination = _field(response, "pagination")
                total_pages = _field(pagination, "total_pages")
                if total_pages is None:
                    total_pages = _field(pagination, "totalPages")
                try:
                    last_page = max(1, int(total_pages))
                except (TypeError, ValueError):
                    last_page = page
                if page >= min(last_page, _MAX_LIST_PAGES):
                    break
                page += 1

            return sources

        return self._run("list_context", operation)

    def recall_context(
        self,
        session_id: str,
        query: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Recall nonempty chunk text for ready Session sources."""

        def operation(client: Any) -> list[dict[str, Any]]:
            response = client.search.execute(
                q=query,
                container_tag=session_id,
                limit=limit,
                filters={"AND": [{"key": "kind", "value": "context"}]},
            )
            normalized: list[dict[str, Any]] = []
            for result in (_field(response, "results", []) or []):
                chunks = _field(result, "chunks", []) or []
                parts = [
                    str(_field(chunk, "content", "") or "").strip()
                    for chunk in chunks
                ]
                text = "\n".join(part for part in parts if part)
                if not text:
                    text = str(_field(result, "content", "") or "").strip()
                if not text:
                    continue
                try:
                    score = float(_field(result, "score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                document_id = str(
                    _field(result, "document_id")
                    or _field(result, "documentId")
                    or ""
                ).strip()
                normalized.append(
                    {
                        "content": text,
                        "metadata": _metadata(result),
                        "score": score,
                        "document_id": document_id or None,
                    }
                )
            return normalized

        return self._run("recall_context", operation)

    def delete_context(self, session_id: str, document_id: str) -> bool:
        """Delete only a context document verified to belong to this session."""
        owned_ids = {source["id"] for source in self.list_context(session_id)}
        if document_id not in owned_ids:
            return False

        def operation(client: Any) -> bool:
            client.documents.delete(document_id)
            return True

        return self._run("delete_context", operation)

    def clear_session(self, session_id: str) -> bool:
        """Delete every provider document scoped to a Hub session."""

        def operation(client: Any) -> bool:
            result = client.documents.delete_bulk(container_tags=[session_id])
            return _field(result, "success", False) is True

        return self._run("clear_session", operation)
