-- init-db/01-extensions.sql
-- Platform Engine: PostgreSQL extensions (docker-entrypoint-initdb.d)
-- Requires custom image: docker/postgres (pgvector + Apache AGE + pg_cron)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- AGE default search path for init scripts in this session
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
