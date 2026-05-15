-- Migration 008: pgvector-backed corpus retrieval (the architecture locked in
-- the Master Plan rev 2.4 — Cohere Embed v4 → Neon pgvector → Cohere Rerank 3.5).
--
-- Until this migration ran the demo had no real corpus store: VECTOR_BACKEND=supermemory
-- routed retrieval through Supermemory's native search (which bypasses Cohere entirely
-- and was empty besides), so the Hub generated from Gemini's general training only.

CREATE EXTENSION IF NOT EXISTS vector;

-- Cohere Embed v4 returns 1024-dim float vectors for embed-english-v4.0
CREATE TABLE IF NOT EXISTS clause_chunks (
    id           BIGSERIAL PRIMARY KEY,
    chunk_uid    TEXT UNIQUE NOT NULL,                       -- stable hash of source+offset+text
    title        TEXT NOT NULL,
    category     TEXT,                                        -- one of the 12 hub categories, when applicable
    source_system TEXT NOT NULL DEFAULT 'curated',            -- 'curated' | 'edgar' | 'cuad' | 'maud'
    document_id  INT,                                         -- FK to documents when sourced from ma_corpus_db
    page         INT,
    posture      TEXT,                                        -- 'buy' | 'sell' | 'neutral' | NULL
    jurisdiction TEXT,
    deal_structure TEXT,
    text         TEXT NOT NULL,
    embedding    vector(1024) NOT NULL,                       -- Cohere Embed v4 dimension
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- IVFFlat is the standard pgvector ANN index for cosine distance. Lists tuned
-- for ~10k rows; rebuild with higher `lists` if the corpus grows past 100k.
CREATE INDEX IF NOT EXISTS idx_clause_chunks_embedding
    ON clause_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_clause_chunks_category ON clause_chunks(category);
CREATE INDEX IF NOT EXISTS idx_clause_chunks_posture  ON clause_chunks(posture);
CREATE INDEX IF NOT EXISTS idx_clause_chunks_source   ON clause_chunks(source_system);
