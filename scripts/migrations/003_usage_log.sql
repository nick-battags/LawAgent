-- Migration 003: usage log for kill-switch accounting and audit

CREATE TABLE IF NOT EXISTS usage_log (
    id          BIGSERIAL PRIMARY KEY,
    ip_hash     TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    tokens_in   INT NOT NULL DEFAULT 0,
    tokens_out  INT NOT NULL DEFAULT 0,
    latency_ms  INT,
    status      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS usage_log_created_at_idx ON usage_log (created_at);
CREATE INDEX IF NOT EXISTS usage_log_ip_hash_idx ON usage_log (ip_hash);
