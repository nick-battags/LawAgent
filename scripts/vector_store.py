"""ChromaDB vector store for semantic retrieval in the CRAG pipeline.

Supports Ollama nomic-embed-text embeddings with multi-endpoint failover
(primary -> secondary -> ...), and defaults to ChromaDB's built-in embedding
function when no Ollama endpoint is reachable.
PostgreSQL remains the source of truth; ChromaDB syncs from it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Any

import chromadb
import requests

from scripts.ollama_endpoints import endpoint_label, fetch_tags, parse_ollama_base_urls

logger = logging.getLogger(__name__)

_store: VectorStore | None = None
_store_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = VectorStore()
    return _store


class VectorStore:
    def __init__(self, persist_dir: str = "./chroma_data"):
        self.persist_dir = persist_dir
        self._lock = threading.RLock()
        self._ollama_urls = parse_ollama_base_urls()
        self._embed_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        self._embed_timeout = int(os.environ.get("OLLAMA_EMBED_TIMEOUT_SEC", "180"))
        self._upsert_batch_size = max(1, int(os.environ.get("VECTOR_UPSERT_BATCH_SIZE", "64")))
        self._upsert_min_batch_size = max(1, int(os.environ.get("VECTOR_UPSERT_MIN_BATCH_SIZE", "8")))
        self._active_embedding_url: str | None = None
        self._active_embedding_backend: str = "none"

        self.client = chromadb.PersistentClient(path=persist_dir)
        self._embedding_fn = self._resolve_embedding_fn()
        self.collection = self._open_collection()
        try:
            self._last_vector_count = self.collection.count()
        except Exception as exc:
            if self._is_recoverable_chroma_error(exc):
                logger.warning("Chroma index appears corrupted; rebuilding collection: %s", exc)
                self._rebuild_collection()
                self._last_vector_count = self.collection.count()
            else:
                raise
        logger.info(
            "ChromaDB initialized (%s): %d vectors in collection",
            self._embedding_label,
            self._last_vector_count,
        )

    @staticmethod
    def _is_recoverable_chroma_error(exc: Exception) -> bool:
        message = str(exc).lower()
        markers = (
            "error loading hnsw index",
            "hnsw segment reader",
            "error constructing hnsw segment reader",
            "backfill request to compactor",
        )
        return any(marker in message for marker in markers)

    def _open_collection(self):
        return self.client.get_or_create_collection(
            name="lawagent_corpus",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _rebuild_collection(self) -> None:
        with self._lock:
            try:
                self.client.delete_collection("lawagent_corpus")
            except Exception:
                pass
            self.collection = self._open_collection()
            self._last_vector_count = 0

    def _build_ollama_embedding_fn(self, base_url: str):
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

        return OllamaEmbeddingFunction(
            url=f"{base_url}/api/embeddings",
            model_name=self._embed_model,
            timeout=self._embed_timeout,
        )

    @staticmethod
    def _looks_like_timeout(exc: Exception) -> bool:
        msg = str(exc).lower()
        timeout_markers = (
            "timed out",
            "readtimeout",
            "read timeout",
            "connecttimeout",
            "connect timeout",
            "time out",
        )
        return any(marker in msg for marker in timeout_markers)

    def _resolve_embedding_fn(self):
        for idx, ollama_url in enumerate(self._ollama_urls):
            try:
                fetch_tags(ollama_url, timeout=2)
                self._active_embedding_url = ollama_url
                self._active_embedding_backend = endpoint_label(idx)
                self._embedding_label = f"ollama/{self._embed_model}@{self._active_embedding_backend}"
                logger.info(
                    "Using Ollama embedding model %s via %s endpoint (%s)",
                    self._embed_model,
                    self._active_embedding_backend,
                    ollama_url,
                )
                return self._build_ollama_embedding_fn(ollama_url)
            except requests.RequestException:
                continue

        self._active_embedding_url = None
        self._active_embedding_backend = "none"
        self._embedding_label = "default/all-MiniLM-L6-v2"
        logger.info("No reachable Ollama embedding endpoints; using ChromaDB default embedding")
        return chromadb.utils.embedding_functions.DefaultEmbeddingFunction()

    def _switch_embedding_endpoint(self, exclude: set[str] | None = None) -> bool:
        exclude = exclude or set()
        for idx, ollama_url in enumerate(self._ollama_urls):
            if ollama_url in exclude:
                continue
            try:
                fetch_tags(ollama_url, timeout=2)
                self._active_embedding_url = ollama_url
                self._active_embedding_backend = endpoint_label(idx)
                self._embedding_fn = self._build_ollama_embedding_fn(ollama_url)
                self._embedding_label = f"ollama/{self._embed_model}@{self._active_embedding_backend}"
                self.collection = self.client.get_or_create_collection(
                    name="lawagent_corpus",
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                try:
                    self._last_vector_count = self.collection.count()
                except Exception:
                    self._last_vector_count = 0
                logger.warning(
                    "Embedding failover active: switched to %s endpoint (%s)",
                    self._active_embedding_backend,
                    ollama_url,
                )
                return True
            except requests.RequestException:
                continue
        return False

    def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        if not chunks:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str]] = []
        seen: set[str] = set()
        for chunk in chunks:
            text = chunk.get("text", "")
            if not text.strip():
                continue
            stable_hash = hashlib.sha256(
                f"{chunk.get('document_id', 0)}:{chunk.get('page', 0)}:{text[:200]}".encode()
            ).hexdigest()[:16]
            chunk_id = f"chunk_{chunk.get('document_id', 0)}_{chunk.get('page', 0)}_{stable_hash}"
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            ids.append(chunk_id)
            documents.append(text)
            metadatas.append({
                "document_id": str(chunk.get("document_id", "")),
                "title": str(chunk.get("title", "")),
                "category": str(chunk.get("category", "")),
                "page": str(chunk.get("page", "")),
                "source_system": str(chunk.get("source_system", "")),
                "jurisdiction": str(chunk.get("jurisdiction", "")),
                "deal_stance": str(chunk.get("deal_stance", "")),
                "deal_structure": str(chunk.get("deal_structure", "")),
            })

        def upsert_once() -> int:
            batch_size = max(self._upsert_batch_size, self._upsert_min_batch_size)
            added_local = 0
            i = 0
            while i < len(ids):
                current = min(batch_size, len(ids) - i)
                try:
                    with self._lock:
                        self.collection.upsert(
                            ids=ids[i : i + current],
                            documents=documents[i : i + current],
                            metadatas=metadatas[i : i + current],
                        )
                        try:
                            self._last_vector_count = self.collection.count()
                        except Exception:
                            pass
                    added_local += current
                    i += current
                except Exception as exc:
                    if self._looks_like_timeout(exc) and current > self._upsert_min_batch_size:
                        batch_size = max(self._upsert_min_batch_size, current // 2)
                        logger.warning(
                            "Vector upsert timeout at batch=%d; reducing batch size to %d and retrying",
                            current,
                            batch_size,
                        )
                        continue
                    raise
            return added_local

        try:
            return upsert_once()
        except Exception:
            if self._active_embedding_url and self._switch_embedding_endpoint(exclude={self._active_embedding_url}):
                return upsert_once()
            raise

    def query(
        self,
        query_text: str,
        top_k: int = 4,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            try:
                current_count = self.collection.count()
                self._last_vector_count = current_count
            except Exception as exc:
                if self._is_recoverable_chroma_error(exc):
                    logger.warning("Chroma query detected corrupted index; rebuilding collection")
                    self._rebuild_collection()
                    current_count = 0
                else:
                    raise
            if current_count == 0:
                return []

        where = {"category": category} if category else None

        def query_once():
            with self._lock:
                n = min(top_k, self.collection.count())
                return self.collection.query(
                    query_texts=[query_text],
                    n_results=n,
                    where=where,
                )

        try:
            results = query_once()
        except Exception:
            if self._active_embedding_url and self._switch_embedding_endpoint(exclude={self._active_embedding_url}):
                results = query_once()
            else:
                raise

        output: list[dict[str, Any]] = []
        for i, doc_text in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0.0
            output.append({
                "text": doc_text,
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "page": meta.get("page", ""),
                "source_system": meta.get("source_system", ""),
                "document_id": meta.get("document_id", ""),
                "jurisdiction": meta.get("jurisdiction", ""),
                "deal_stance": meta.get("deal_stance", ""),
                "deal_structure": meta.get("deal_structure", ""),
                "distance": distance,
                "score": max(1, int((1.0 - distance) * 10)) if distance else 5,
            })
        return output

    def sync_from_postgres(self) -> dict[str, Any]:
        from scripts.ma_corpus_db import get_db

        db = get_db()
        chunks = db.get_all_chunks()
        if not chunks:
            logger.info("No chunks in PostgreSQL to sync")
            return {"synced": 0, "total": self.collection.count()}

        with self._lock:
            try:
                before = self.collection.count()
            except Exception:
                before = self._last_vector_count
        added = self.add_chunks(chunks)
        with self._lock:
            try:
                after = self.collection.count()
            except Exception:
                after = self._last_vector_count

        logger.info(
            "Vector sync complete: %d chunks processed (before=%d, after=%d)",
            added,
            before,
            after,
        )
        return {"synced": added, "before": before, "after": after}

    def sync_documents(self, document_ids: list[int]) -> dict[str, Any]:
        from scripts.ma_corpus_db import get_db

        with self._lock:
            try:
                before = self.collection.count()
            except Exception:
                before = self._last_vector_count

        if not document_ids:
            return {"synced": 0, "before": before, "after": before}

        db = get_db()
        chunks = db.get_chunks_for_documents(document_ids)
        added = self.add_chunks(chunks)

        with self._lock:
            try:
                after = self.collection.count()
            except Exception:
                after = self._last_vector_count

        logger.info(
            "Vector partial sync complete for docs=%s: %d chunks (before=%d, after=%d)",
            document_ids,
            added,
            before,
            after,
        )
        return {
            "synced": added,
            "before": before,
            "after": after,
            "document_ids": document_ids,
        }

    def remove_document(self, document_id: int) -> int:
        with self._lock:
            existing = self.collection.get(where={"document_id": str(document_id)})
            ids = existing.get("ids") or []
            if ids:
                self.collection.delete(ids=ids)
            removed = len(ids)
        logger.info("Removed %d vector chunks for document_id=%s", removed, document_id)
        return removed

    def clear(self) -> None:
        with self._lock:
            self.client.delete_collection("lawagent_corpus")
            self.collection = self.client.get_or_create_collection(
                name="lawagent_corpus",
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
            self._last_vector_count = 0

    def count(self) -> int:
        with self._lock:
            try:
                self._last_vector_count = self.collection.count()
            except Exception as exc:
                if self._is_recoverable_chroma_error(exc):
                    logger.warning("Chroma count detected corrupted index; rebuilding collection")
                    self._rebuild_collection()
                    self._last_vector_count = 0
                else:
                    raise
            return self._last_vector_count

    def status(self) -> dict[str, Any]:
        with self._lock:
            try:
                self._last_vector_count = self.collection.count()
            except Exception as exc:
                if self._is_recoverable_chroma_error(exc):
                    logger.warning("Chroma status detected corrupted index; rebuilding collection")
                    self._rebuild_collection()
                    self._last_vector_count = 0
                else:
                    raise
        return {
            "vector_count": self._last_vector_count,
            "embedding": self._embedding_label,
            "embedding_backend": self._active_embedding_backend,
            "embedding_urls_configured": len(self._ollama_urls),
            "persist_dir": self.persist_dir,
        }
