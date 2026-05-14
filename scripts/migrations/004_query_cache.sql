-- Migration 004: query cache for /api/v2/analyze deduplication

CREATE TABLE IF NOT EXISTS query_cache (
    cache_key   TEXT PRIMARY KEY,
    response    JSONB NOT NULL,
    hits        INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS query_cache_expires_at_idx ON query_cache (expires_at);
