#!/bin/bash
# PostgREST role setup. Runs before the migrations (alphabetical order).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Role that PostgREST switches into for authenticated (JWT) requests.
    CREATE ROLE service_role NOLOGIN;

    -- Role for requests without a JWT. Deliberately powerless.
    CREATE ROLE anon NOLOGIN;

    -- The role PostgREST actually connects as; it only borrows the two above.
    CREATE ROLE authenticator LOGIN PASSWORD '${AUTHENTICATOR_PASSWORD}' NOINHERIT;
    GRANT service_role TO authenticator;
    GRANT anon TO authenticator;
EOSQL
