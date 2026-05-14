-- Migration 005: supermemory_id tracking columns
-- Allows linking Postgres rows to their Supermemory memory IDs for audit/cleanup.

ALTER TABLE clause_chunks
    ADD COLUMN IF NOT EXISTS supermemory_id TEXT;

CREATE INDEX IF NOT EXISTS clause_chunks_supermemory_id_idx
    ON clause_chunks (supermemory_id)
    WHERE supermemory_id IS NOT NULL;
