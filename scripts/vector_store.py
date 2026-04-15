"""ChromaDB vector store for semantic retrieval in the CRAG pipeline.

Supports Ollama nomic-embed-text embeddings when available, with automatic
fallback to ChromaDB's default embedding function (all-MiniLM-L6-v2).
PostgreSQL remains the source of truth; ChromaDB syncs from it.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import chromadb

logger = logging.getLogger(__name__)

_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


class VectorStore:
    def __init__(self, persist_dir: str = "./chroma_data"):
        self.persist_dir = persist_dir
        self.client = chromadb.PersistentClient(path=persist_dir)
        self._embedding_fn = self._resolve_embedding_fn()
        self.collection = self.client.get_or_create_collection(
            name="lawagent_corpus",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB initialized (%s): %d vectors in collection",
            self._embedding_label,
            self.collection.count(),
        )

    def _resolve_embedding_fn(self):
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        embed_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        try:
            import requests

            r = requests.get(f"{ollama_url}/api/tags", timeout=2)
            if r.ok:
                from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

                self._embedding_label = f"ollama/{embed_model}"
                logger.info("Using Ollama embedding model: %s", embed_model)
                return OllamaEmbeddingFunction(
                    url=f"{ollama_url}/api/embeddings",
                    model_name=embed_model,
                )
        except Exception:
            pass
        self._embedding_label = "default/all-MiniLM-L6-v2"
        logger.info("Ollama unavailable — using ChromaDB default embedding")
        return chromadb.utils.embedding_functions.DefaultEmbeddingFunction()

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

        batch_size = 500
        added = 0
        for i in range(0, len(ids), batch_size):
            self.collection.upsert(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )
            added += len(ids[i : i + batch_size])
        return added

    def query(
        self,
        query_text: str,
        top_k: int = 4,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        where = {"category": category} if category else None
        n = min(top_k, self.collection.count())
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n,
            where=where,
        )
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
        before = self.collection.count()
        added = self.add_chunks(chunks)
        after = self.collection.count()
        logger.info(
            "Vector sync complete: %d chunks processed (before=%d, after=%d)",
            added, before, after,
        )
        return {"synced": added, "before": before, "after": after}

    def clear(self) -> None:
        self.client.delete_collection("lawagent_corpus")
        self.collection = self.client.get_or_create_collection(
            name="lawagent_corpus",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self.collection.count()

    def status(self) -> dict[str, Any]:
        return {
            "vector_count": self.collection.count(),
            "embedding": self._embedding_label,
            "persist_dir": self.persist_dir,
        }
