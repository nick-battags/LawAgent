"""pgvector-backed corpus retrieval store (the canonical architecture per
Master Plan rev 2.4 § Locked decisions and 02c_Editing_Hub.md § Pipeline).

Cohere Embed v4 embeds the query → Neon pgvector cosine-similarity search →
candidates handed to Cohere Rerank 3.5 in scripts/hub_pipeline._retrieve_and_rerank.

Provides the same query()/add_chunks()/count()/status()/clear() surface as
scripts/vector_store.VectorStore and scripts/supermemory_store.SupermemoryCorpusStore
so the demo factory can swap backends via VECTOR_BACKEND env var.

Env vars:
  DATABASE_URL              — required (Neon connection string from Secret Manager)
  PGVECTOR_TABLE            — default "clause_chunks"
  PGVECTOR_TOP_K            — default retrieval k (default 8)
  COHERE_API_KEY            — required for embedding queries (resolved via VertexProvider)
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


def _format_vector_literal(vec: list[float]) -> str:
    """Format a Python list[float] as a pgvector text literal: '[v1,v2,...]'.

    pgvector accepts string casting via `::vector`, which avoids a hard dependency
    on the optional `pgvector` Python adapter (we already pin psycopg[binary]).
    """
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


class PgvectorCorpusStore:
    """Cohere-embedded, pgvector-backed corpus store for the demo retrieval path."""

    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL", "")
        if not self.database_url:
            raise RuntimeError("PgvectorCorpusStore requires DATABASE_URL env var")
        self.table = os.environ.get("PGVECTOR_TABLE", "clause_chunks")
        self.default_top_k = int(os.environ.get("PGVECTOR_TOP_K", "8"))
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url)

    def _embed_query(self, text: str) -> list[float] | None:
        """Embed via Cohere Embed v4 with input_type=search_query."""
        try:
            from scripts.llm_provider import get_llm, VertexProvider
            provider = get_llm()
            if not isinstance(provider, VertexProvider):
                logger.warning(
                    "PgvectorCorpusStore: LLM_PROVIDER is not vertex; cannot Cohere-embed query"
                )
                return None
            vectors = provider.embed([text], input_type="search_query")
            return vectors[0] if vectors else None
        except Exception as exc:
            logger.warning("Cohere query embed failed: %s", exc)
            return None

    def _embed_documents(self, texts: list[str]) -> list[list[float]] | None:
        """Embed via Cohere Embed v4 with input_type=search_document for ingestion."""
        try:
            from scripts.llm_provider import get_llm, VertexProvider
            provider = get_llm()
            if not isinstance(provider, VertexProvider):
                logger.warning(
                    "PgvectorCorpusStore: LLM_PROVIDER is not vertex; cannot embed documents"
                )
                return None
            return provider.embed(texts, input_type="search_document")
        except Exception as exc:
            logger.error("Cohere document embed failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public surface (mirrors VectorStore + SupermemoryCorpusStore)
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("PgvectorCorpusStore unavailable: %s", exc)
            return False

    def query(
        self,
        query_text: str,
        top_k: int | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cohere-embed query → pgvector cosine-similarity top-k.

        Returns dicts with the same shape as VectorStore.query so downstream
        callers (hub_pipeline._retrieve_and_rerank) don't need to branch.
        """
        if not query_text:
            return []
        k = top_k or self.default_top_k

        vec = self._embed_query(query_text)
        if vec is None:
            return []
        vec_lit = _format_vector_literal(vec)

        # WHERE embedding IS NOT NULL excludes any legacy migration-001 rows
        # that pre-dated the Hub corpus seeding.
        where_extra = "AND category = %s" if category else ""
        sql = f"""
            SELECT chunk_uid, title, category, source_system, document_id, page,
                   posture, jurisdiction, deal_structure, text,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM {self.table}
            WHERE embedding IS NOT NULL {where_extra}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params: list[Any] = [vec_lit]
        if category:
            params.append(category)
        params.extend([vec_lit, k])

        try:
            with self._lock, self._connect() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        except Exception as exc:
            logger.error("Pgvector query failed: %s", exc)
            return []

        out: list[dict[str, Any]] = []
        for r in rows:
            similarity = float(r[10]) if r[10] is not None else 0.0
            out.append({
                "text": r[9] or "",
                "title": r[1] or "",
                "category": r[2] or "",
                "page": str(r[5] or ""),
                "source_system": r[3] or "pgvector",
                "document_id": str(r[4] or ""),
                "jurisdiction": r[7] or "",
                "deal_stance": r[6] or "",          # mirrors VectorStore field name
                "deal_structure": r[8] or "",
                "distance": round(1.0 - similarity, 4),
                "score": max(1, int(similarity * 10)),
            })
        return out

    def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Embed via Cohere Embed v4 and INSERT (or UPDATE on chunk_uid conflict).

        Each chunk dict expects: text (required), title, category, source_system,
        document_id, page, posture, jurisdiction, deal_structure.
        """
        if not chunks:
            return 0
        texts = [c.get("text", "") for c in chunks]
        embeddings = self._embed_documents(texts)
        if embeddings is None:
            return 0
        if len(embeddings) != len(chunks):
            logger.error(
                "Cohere returned %d embeddings for %d chunks; aborting ingest",
                len(embeddings), len(chunks),
            )
            return 0

        rows: list[tuple] = []
        seen: set[str] = set()
        for chunk, vec in zip(chunks, embeddings):
            text = chunk.get("text", "")
            if not text.strip():
                continue
            uid_seed = (
                f"{chunk.get('source_system', 'curated')}:"
                f"{chunk.get('document_id', '')}:"
                f"{chunk.get('page', '')}:"
                f"{text[:240]}"
            )
            chunk_uid = chunk.get("chunk_uid") or hashlib.sha256(uid_seed.encode()).hexdigest()[:32]
            if chunk_uid in seen:
                continue
            seen.add(chunk_uid)
            rows.append((
                chunk_uid,
                chunk.get("title", "") or "untitled",
                chunk.get("category"),
                chunk.get("source_system", "curated"),
                int(chunk["document_id"]) if chunk.get("document_id") else None,
                int(chunk["page"]) if chunk.get("page") else None,
                chunk.get("posture"),
                chunk.get("jurisdiction"),
                chunk.get("deal_structure"),
                text,
                _format_vector_literal(vec),
            ))

        if not rows:
            return 0

        # ON CONFLICT (chunk_uid) WHERE chunk_uid IS NOT NULL matches the
        # partial unique index uniq_clause_chunks_chunk_uid (migration 008).
        sql = f"""
            INSERT INTO {self.table}
                (chunk_uid, title, category, source_system, document_id, page,
                 posture, jurisdiction, deal_structure, text, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (chunk_uid) WHERE chunk_uid IS NOT NULL DO UPDATE SET
                title = EXCLUDED.title,
                category = EXCLUDED.category,
                source_system = EXCLUDED.source_system,
                document_id = EXCLUDED.document_id,
                page = EXCLUDED.page,
                posture = EXCLUDED.posture,
                jurisdiction = EXCLUDED.jurisdiction,
                deal_structure = EXCLUDED.deal_structure,
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding
        """
        try:
            with self._lock, self._connect() as conn, conn.cursor() as cur:
                cur.executemany(sql, rows)
                conn.commit()
            logger.info("PgvectorCorpusStore: upserted %d chunks", len(rows))
            return len(rows)
        except Exception as exc:
            logger.error("Pgvector upsert failed: %s", exc)
            return 0

    def count(self) -> int:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self.table}")
                return int(cur.fetchone()[0])
        except Exception:
            return 0

    def clear(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {self.table} RESTART IDENTITY")
            conn.commit()

    def status(self) -> dict[str, Any]:
        return {
            "backend": "pgvector",
            "table": self.table,
            "vector_count": self.count(),
            "embedding": "cohere/embed-english-v4.0",
            "embedding_backend": "cohere",
        }
