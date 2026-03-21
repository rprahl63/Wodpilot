-- WODpilot initial schema
-- Run against your Supabase project via the SQL editor or psql.

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Users ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    telegram_id         BIGINT UNIQUE NOT NULL,
    username            TEXT,
    full_name           TEXT,
    role                TEXT NOT NULL DEFAULT 'user'  CHECK (role IN ('admin','user')),
    -- Garmin (encrypted)
    garmin_email        TEXT,
    garmin_password_enc TEXT,
    -- LLM (encrypted)
    llm_api_key_enc     TEXT,
    llm_model           TEXT DEFAULT 'claude-sonnet-4-20250514',
    -- Heart-rate profile
    hr_max              INT DEFAULT 190,
    hr_rest             INT DEFAULT 55,
    -- Preferences
    timezone            TEXT DEFAULT 'Europe/Berlin',
    briefing_enabled    BOOLEAN DEFAULT TRUE,
    -- Rate limiting
    api_calls_today     INT DEFAULT 0,
    api_calls_reset_at  DATE DEFAULT CURRENT_DATE,
    -- GDPR consent
    consent_given_at    TIMESTAMPTZ,
    -- Meta
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Invite codes ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invite_codes (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    created_by  BIGINT REFERENCES users(id),
    used_by     BIGINT REFERENCES users(id),
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Activities (Garmin) ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activities (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    garmin_id       TEXT,
    activity_type   TEXT,          -- e.g. 'running', 'strength_training', 'cycling'
    started_at      TIMESTAMPTZ NOT NULL,
    duration_s      INT,           -- seconds
    distance_m      FLOAT,         -- metres
    hr_avg          INT,
    hr_max          INT,
    calories        INT,
    tss             FLOAT,         -- Training Stress Score
    raw_json        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, garmin_id)
);

-- ─── WODs (shared) ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wods (
    id          BIGSERIAL PRIMARY KEY,
    date        DATE NOT NULL,
    source      TEXT NOT NULL,     -- box name / URL
    content     TEXT NOT NULL,
    scraped_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, source)
);

-- ─── Conversations ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_time
    ON conversations(user_id, created_at DESC);

-- ─── Coach Memory (semantic key-value) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS coach_memory (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT,              -- e.g. 'injury', 'pr', 'goal', 'preference'
    embedding   vector(1536),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_coach_memory_user ON coach_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_coach_memory_embedding
    ON coach_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ─── Memory Episodes (episodic) ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_episodes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    category    TEXT,              -- 'pr', 'injury', 'scaling', 'achievement'
    metadata    JSONB DEFAULT '{}',
    embedding   vector(1536),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodes_user ON memory_episodes(user_id);
CREATE INDEX IF NOT EXISTS idx_episodes_embedding
    ON memory_episodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ─── Memory Procedural (coaching style) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_procedural (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    coaching_style  TEXT DEFAULT 'balanced'
                        CHECK (coaching_style IN ('direct','supportive','technical','balanced')),
    preferred_language TEXT DEFAULT 'de',
    notes           TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Global config ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default WOD sources (empty – admin configures via dashboard)
INSERT INTO config (key, value) VALUES
    ('wod_sources', '[]'),
    ('garmin_sync_cron', '0 5 * * *'),
    ('wod_scrape_cron', '30 5 * * *'),
    ('morning_briefing_cron', '0 7 * * *')
ON CONFLICT (key) DO NOTHING;

-- ─── Helper: auto-update updated_at ──────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_users_updated
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_memory_updated
    BEFORE UPDATE ON coach_memory
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
