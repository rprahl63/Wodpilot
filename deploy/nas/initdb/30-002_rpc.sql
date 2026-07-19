-- Vector similarity search RPC functions for WODpilot.
-- Run in Supabase SQL editor after 001_initial.sql.

-- Search semantic memory (coach_memory) by vector similarity
CREATE OR REPLACE FUNCTION search_coach_memory(
    p_user_id   BIGINT,
    p_embedding vector(1536),
    p_limit     INT DEFAULT 5
)
RETURNS TABLE (
    key         TEXT,
    value       TEXT,
    category    TEXT,
    similarity  FLOAT
)
LANGUAGE SQL STABLE AS $$
    SELECT
        key,
        value,
        category,
        1 - (embedding <=> p_embedding) AS similarity
    FROM coach_memory
    WHERE user_id = p_user_id
      AND embedding IS NOT NULL
    ORDER BY embedding <=> p_embedding
    LIMIT p_limit;
$$;

-- Search episodic memory by vector similarity
CREATE OR REPLACE FUNCTION search_episodes(
    p_user_id   BIGINT,
    p_embedding vector(1536),
    p_limit     INT DEFAULT 5
)
RETURNS TABLE (
    content     TEXT,
    category    TEXT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ,
    similarity  FLOAT
)
LANGUAGE SQL STABLE AS $$
    SELECT
        content,
        category,
        metadata,
        created_at,
        1 - (embedding <=> p_embedding) AS similarity
    FROM memory_episodes
    WHERE user_id = p_user_id
      AND embedding IS NOT NULL
    ORDER BY embedding <=> p_embedding
    LIMIT p_limit;
$$;
