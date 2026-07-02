-- scripts/init-extensions.sql
-- Run from project root:
--   psql -U postgres -d vita_db -f scripts/init-extensions.sql

\echo 'Applying init-db/01-extensions.sql...'
\ir init-db/01-extensions.sql

\echo 'Applying init-db/02-gsw-hnsw-index.sql...'
\ir init-db/02-gsw-hnsw-index.sql

\echo 'Applying init-db/03-age-graph.sql...'
\ir init-db/03-age-graph.sql

\echo 'Applying init-db/04-pg-cron-jobs.sql...'
\ir init-db/04-pg-cron-jobs.sql
