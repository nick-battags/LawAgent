-- Migration 006: session memory ledger
-- Local audit log of all Supermemory write attempts (success and blocked).
-- Never stores raw content — only metadata, write outcome, and char count.

CREATE TABLE IF NOT EXISTS session_memory_ledger (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    char_count      INT NOT NULL,
    outcome         TEXT NOT NULL,   -- 'written' | 'blocked_length' | 'blocked_pii' | 'blocked_firewall' | 'error'
    supermemory_id  TEXT,            -- populated on successful write
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_memory_ledger_session_id_idx
    ON session_memory_ledger (session_id);
CREATE INDEX IF NOT EXISTS session_memory_ledger_created_at_idx
    ON session_memory_ledger (created_at);
