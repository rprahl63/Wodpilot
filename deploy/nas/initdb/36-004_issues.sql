-- WODpilot migration 004 – product issues (bug reports, feature requests)
-- Run against your Supabase project via the SQL editor or psql.

-- ─── Issues ──────────────────────────────────────────────────────────────────
-- Feedback about WODpilot itself, raised by the coach agent from chat.
--
-- status is the workflow the issue skill drives:
--   open        – reported, nobody working on it
--   in_progress – claimed by a dev session
--   done        – implemented AND deployed (the reporter is notified then)
--   rejected    – won't do; the reason goes to the reporter
--
-- ON DELETE CASCADE like every other table: /delete promises complete removal
-- and a free-text issue body can carry personal data. Anything worth keeping
-- has landed in the repo by the time the issue is resolved.
CREATE TABLE IF NOT EXISTS issues (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'other'
                    CHECK (kind IN ('bug','feature','question','other')),
    priority    TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low','normal','high')),
    status      TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','in_progress','done','rejected')),
    resolution  TEXT,                             -- what was done / why rejected
    source      TEXT NOT NULL DEFAULT 'chat',     -- 'chat' | 'admin'
    resolved_at TIMESTAMPTZ,
    notified_at TIMESTAMPTZ,                      -- reporter told about the outcome
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_issues_user ON issues(user_id, created_at DESC);

-- ─── Trigger (set_updated_at() exists from 001) ──────────────────────────────
CREATE OR REPLACE TRIGGER trg_issues_updated
    BEFORE UPDATE ON issues
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
