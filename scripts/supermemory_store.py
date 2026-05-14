"""Supermemory-backed corpus retrieval store for the demo pipeline.

Wraps the Supermemory Python SDK to retrieve from the shared M&A corpus
under SUPERMEMORY_CORPUS_TAG. Provides the same query/add interface as
VectorStore so the CRAG pipeline can swap backends via VECTOR_BACKEND env var.

Env vars:
  SUPERMEMORY_API_KEY   — required
  SUPERMEMORY_CORPUS_TAG — container tag for the shared M&A corpus (default: lawagent-corpus)
  SUPERMEMORY_TOP_K      — default top-k for retrieval (default: 8)
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

_demo_store: SupermemoryCorpusStore | None = None
_demo_store_lock = threading.Lock()


class SupermemoryCorpusStore:
    """Corpus retrieval via Supermemory Memory Graph.

    Provides query() and add() with the same return shape as VectorStore,
    so the CRAG pipeline code is backend-agnostic.
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("SUPERMEMORY_API_KEY", "")
        self.corpus_tag = os.environ.get("SUPERMEMORY_CORPUS_TAG", "lawagent-corpus")
        self.default_top_k = int(os.environ.get("SUPERMEMORY_TOP_K", "8"))
        self._client: Any = None
        self._client_lock = threading.Lock()

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self.api_key:
                        raise RuntimeError("SUPERMEMORY_API_KEY env var not set")
                    import supermemory
                    self._client = supermemory.Supermemory(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        try:
            self._get_client()
            return True
        except Exception as exc:
            logger.warning("SupermemoryCorpusStore unavailable: %s", exc)
            return False

    def query(
        self,
        query_text: str,
        top_k: int | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve top-k corpus chunks for query_text.

        Returns list of dicts matching VectorStore.query() shape:
          {text, title, category, page, source_system, document_id,
           jurisdiction, deal_stance, deal_structure, distance, score}
        """
        k = top_k or self.default_top_k
        client = self._get_client()
        try:
            filters: dict[str, Any] = {"AND": [{"key": "kind", "value": "corpus_chunk"}]}
            if category:
                filters["AND"].append({"key": "category", "value": category})

            response = client.search.execute(
                q=query_text,
                container_tag=self.corpus_tag,
                limit=k,
                filters=filters,
            )
            return [self._normalize_result(r) for r in (response.results or [])]
        except Exception as exc:
            logger.error("Supermemory corpus query failed: %s", exc)
            return []

    def add(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        container_tag: str | None = None,
    ) -> str | None:
        """Add a chunk to Supermemory. Returns the memory ID or None on failure."""
        client = self._get_client()
        meta = {"kind": "corpus_chunk", **(metadata or {})}
        tag = container_tag or self.corpus_tag
        try:
            result = client.memories.add(
                content=content,
                container_tag=tag,
                metadata=meta,
            )
            return getattr(result, "id", None)
        except Exception as exc:
            logger.error("Supermemory add failed: %s", exc)
            return None

    def status(self) -> dict[str, Any]:
        return {
            "backend": "supermemory",
            "corpus_tag": self.corpus_tag,
            "available": self.is_available(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_result(result: Any) -> dict[str, Any]:
        """Map Supermemory search result to the VectorStore output shape."""
        meta: dict[str, Any] = getattr(result, "metadata", {}) or {}
        content: str = getattr(result, "content", "") or ""
        score_raw: float = getattr(result, "score", 0.5) or 0.5

        return {
            "text": content,
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "page": str(meta.get("page", "")),
            "source_system": meta.get("source_system", "supermemory"),
            "document_id": str(meta.get("document_id", "")),
            "jurisdiction": meta.get("jurisdiction", ""),
            "deal_stance": meta.get("deal_stance", ""),
            "deal_structure": meta.get("deal_structure", ""),
            "distance": round(1.0 - float(score_raw), 4),
            "score": max(1, int(float(score_raw) * 10)),
        }
