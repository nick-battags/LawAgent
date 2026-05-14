-- Migration 001: initial schema
-- Creates core tables if not already present (idempotent).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    category    TEXT,
    source_system TEXT,
    jurisdiction TEXT,
    deal_stance TEXT,
    deal_structure TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clause_chunks (
    id          SERIAL PRIMARY KEY,
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    page        INT,
    text        TEXT NOT NULL,
    embedding   vector(1024),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS clause_chunks_embedding_idx
    ON clause_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS daily_usage (
    id          SERIAL PRIMARY KEY,
    ip_hash     TEXT NOT NULL,
    date        DATE NOT NULL DEFAULT CURRENT_DATE,
    token_count INT NOT NULL DEFAULT 0,
    UNIQUE (ip_hash, date)
);
