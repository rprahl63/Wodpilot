-- Grants for PostgREST. Runs after the migrations have created the tables.
-- service_role mirrors what the Supabase service_role key could do: everything.
-- anon gets nothing, so an unauthenticated request can never read training data.

GRANT USAGE ON SCHEMA public TO service_role;

GRANT ALL ON ALL TABLES    IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- Anything created later (e.g. a future migration) stays reachable too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role;

-- Explicitly ensure anon stays locked out of the schema.
REVOKE ALL ON SCHEMA public FROM anon;
