-- Migration 007: Drafting & Review Hub tables (Phase 2c)

CREATE TYPE IF NOT EXISTS hub_mode AS ENUM ('generate', 'revise', 'review');
CREATE TYPE IF NOT EXISTS hub_posture AS ENUM ('buy', 'sell', 'neutral');
CREATE TYPE IF NOT EXISTS hub_status AS ENUM ('running', 'ready', 'expired', 'failed');
CREATE TYPE IF NOT EXISTS hub_severity AS ENUM ('high', 'med', 'low');
CREATE TYPE IF NOT EXISTS hub_kind AS ENUM ('redline', 'missing_clause');
CREATE TYPE IF NOT EXISTS hub_action AS ENUM ('pending', 'accepted', 'rejected', 'edited', 'dismissed');

CREATE TABLE IF NOT EXISTS hub_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mode            hub_mode NOT NULL,
    posture         hub_posture NOT NULL DEFAULT 'neutral',
    prompt          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours',
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          hub_status NOT NULL DEFAULT 'running',
    gcs_prefix      TEXT,
    decisions       JSONB NOT NULL DEFAULT '[]',
    dismissed_missing JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS hub_sessions_status_expires_idx
    ON hub_sessions (status, expires_at);
CREATE INDEX IF NOT EXISTS hub_sessions_last_activity_idx
    ON hub_sessions (last_activity_at);

CREATE TABLE IF NOT EXISTS hub_changes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES hub_sessions(id) ON DELETE CASCADE,
    clause_anchor   TEXT,
    category        TEXT NOT NULL,
    severity        hub_severity NOT NULL DEFAULT 'med',
    kind            hub_kind NOT NULL DEFAULT 'redline',
    original_text   TEXT,
    proposed_text   TEXT NOT NULL,
    rationale       TEXT NOT NULL,
    source_ref      TEXT,
    current_action  hub_action NOT NULL DEFAULT 'pending',
    current_text    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS hub_changes_session_id_idx
    ON hub_changes (session_id);
