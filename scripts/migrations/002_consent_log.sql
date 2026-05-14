-- Migration 002: consent log for demo mode gate

CREATE TABLE IF NOT EXISTS consent_log (
    id          SERIAL PRIMARY KEY,
    ip_hash     TEXT NOT NULL,
    consented_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    token_hash  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS consent_log_ip_hash_idx ON consent_log (ip_hash);
