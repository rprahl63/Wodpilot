-- WODpilot migration 003 – athlete dashboard, training preferences, weekly plans
-- Run against your Supabase project via the SQL editor or psql.

-- ─── Login tokens (magic links for the athlete dashboard) ────────────────────
CREATE TABLE IF NOT EXISTS login_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT UNIQUE NOT NULL,          -- sha256 hex of the raw token
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_login_tokens_user ON login_tokens(user_id);

-- ─── Training preferences (free text, editable in the dashboard) ─────────────
CREATE TABLE IF NOT EXISTS training_preferences (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preferences_text TEXT NOT NULL DEFAULT '',
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Training plans (one row per user per week) ──────────────────────────────
-- status doubles as the Sunday planning state machine:
--   asked    – question sent, waiting for the user's reply
--   planning – agent is generating the plan (claimed exactly once)
--   planned  – sessions written
--   failed   – agent call failed; fallback/replan may retry
CREATE TABLE IF NOT EXISTS training_plans (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start       DATE NOT NULL,             -- Monday of the planned week
    status           TEXT NOT NULL DEFAULT 'asked'
                         CHECK (status IN ('asked','planning','planned','failed')),
    constraints_text TEXT,                      -- user's reply; NULL when planned from preferences only
    asked_at         TIMESTAMPTZ,
    planned_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, week_start)
);

CREATE INDEX IF NOT EXISTS idx_training_plans_user ON training_plans(user_id, week_start DESC);

-- ─── Plan sessions (results live directly on the session) ────────────────────
CREATE TABLE IF NOT EXISTS plan_sessions (
    id            BIGSERIAL PRIMARY KEY,
    plan_id       BIGINT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date          DATE NOT NULL,
    position      INT NOT NULL DEFAULT 0,       -- ordering within a day
    title         TEXT NOT NULL,                -- e.g. 'Intervalle 6x400m'
    session_type  TEXT,                         -- 'intervals','run','strength','wod','mobility','rest'
    description   TEXT NOT NULL,                -- full session detail (multi-line)
    status        TEXT NOT NULL DEFAULT 'planned'
                      CHECK (status IN ('planned','done','skipped')),
    result_text   TEXT,
    rpe           INT CHECK (rpe BETWEEN 1 AND 10),
    result_notes  TEXT,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_sessions_user_date ON plan_sessions(user_id, date);

-- ─── Triggers (set_updated_at() exists from 001) ─────────────────────────────
CREATE OR REPLACE TRIGGER trg_training_preferences_updated
    BEFORE UPDATE ON training_preferences
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_training_plans_updated
    BEFORE UPDATE ON training_plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_plan_sessions_updated
    BEFORE UPDATE ON plan_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── Config seeds ────────────────────────────────────────────────────────────
INSERT INTO config (key, value) VALUES
    ('weekly_plan_ask_cron', '0 10 * * sun'),
    ('weekly_plan_fallback_cron', '0 18 * * sun')
ON CONFLICT (key) DO NOTHING;
