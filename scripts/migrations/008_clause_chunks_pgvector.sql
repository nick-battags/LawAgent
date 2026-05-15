-- Migration 008: extend clause_chunks for the canonical Cohere → pgvector
-- corpus path (Master Plan rev 2.4 § Locked decisions, 02c § Pipeline).
--
-- The base table from 001_initial_schema.sql already has the right vector(1024)
-- column for Cohere Embed v4. This migration ADDs the metadata columns the Hub
-- needs (title, category, posture, source_system, jurisdiction, deal_structure,
-- chunk_uid for upsert), backfills existing rows, and adds the supporting
-- indexes. The HNSW index on `embedding` from 001 is preserved.
--
-- Safe to re-run: every operation uses IF NOT EXISTS / IF EXISTS guards.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE clause_chunks
    ADD COLUMN IF NOT EXISTS chunk_uid     TEXT,
    ADD COLUMN IF NOT EXISTS title         TEXT,
    ADD COLUMN IF NOT EXISTS category      TEXT,
    ADD COLUMN IF NOT EXISTS source_system TEXT NOT NULL DEFAULT 'curated',
    ADD COLUMN IF NOT EXISTS posture       TEXT,
    ADD COLUMN IF NOT EXISTS jurisdiction  TEXT,
    ADD COLUMN IF NOT EXISTS deal_structure TEXT;

-- Backfill legacy rows that pre-date the Hub schema
UPDATE clause_chunks
SET title = COALESCE(title, 'legacy_' || COALESCE(document_id::TEXT, id::TEXT))
WHERE title IS NULL;

UPDATE clause_chunks
SET source_system = COALESCE(source_system, 'legacy')
WHERE source_system IS NULL OR source_system = '';

-- Generate stable chunk_uid for legacy rows (sha256 of text + id) so the
-- partial unique index below succeeds.
UPDATE clause_chunks
SET chunk_uid = SUBSTRING(ENCODE(DIGEST('legacy:' || id::TEXT || ':' || COALESCE(text, ''), 'sha256'), 'hex') FROM 1 FOR 32)
WHERE chunk_uid IS NULL;

-- Title is non-null going forward (Hub ingest always provides it)
ALTER TABLE clause_chunks ALTER COLUMN title SET NOT NULL;

-- Partial unique constraint so ON CONFLICT (chunk_uid) DO UPDATE works
-- in pgvector_store.add_chunks. Partial keeps any NULL legacy value safe.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_clause_chunks_chunk_uid
    ON clause_chunks(chunk_uid)
    WHERE chunk_uid IS NOT NULL;

-- Supporting indexes for the Hub's category/posture filters
CREATE INDEX IF NOT EXISTS idx_clause_chunks_category ON clause_chunks(category);
CREATE INDEX IF NOT EXISTS idx_clause_chunks_posture  ON clause_chunks(posture);
CREATE INDEX IF NOT EXISTS idx_clause_chunks_source   ON clause_chunks(source_system);
