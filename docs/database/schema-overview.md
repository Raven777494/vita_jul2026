# Schema Overview

Version: 0.3 (P4-4)

## Bootstrap SQL (`init-db/`)

| File | Purpose |
|------|---------|
| `01-extensions.sql` | vector, age, pg_cron |
| `02-gsw-hnsw-index.sql` | HNSW on gsw_eternal_echoes |
| `03-age-graph.sql` | AGE graph shell `vita_memory_graph` (read-only reserve, ADR-002) |
| `04-pg-cron-jobs.sql` | Scheduled cleanup old GSW echoes |

## Core ORM domains (`app/services/db_manager.py`)

| Domain | Notes |
|--------|-------|
| Users / sessions | Conversation state, escalation flags |
| Turns | Message history |
| gsw_eternal_echoes | Vector embeddings (pgvector + HNSW) — **primary semantic recall** (ADR-002) |
| memory_graph | Relational graph nodes (JSONB) — primary structured graph path when writes ship |
| crisis_events | Internal crisis audit (hotline_provided legacy column — not user hotline delivery) |
| reality_facts | KAG verifiable facts |

## Platform extensions

Requires custom image `docker/postgres` for full stack: vector 0.8.x, age 1.5.x, pg_cron 1.6.x.

Local development (`config/.env.local`):

- `DB_HOST=127.0.0.1` must reach `docker compose` postgres (`ports: 5432:5432`)
- `DB_PASSWORD` comes from `config/.env.compose` via `compose_env.py` (never in `.env.local`)
- Start Postgres: `docker compose --env-file config/.env.compose up -d postgres`
- Verify: `python scripts/dev/verify_platform_postgres.py`
- Alignment checker group: `platform_engine`

If another PostgreSQL binds port 5432 without AGE/pg_cron, the app connects but extensions fail — stop the conflicting instance or change the compose port mapping.

## Migrations (P4-1)

Alembic is the primary DDL path. See [migrations.md](migrations.md).

## ER diagram

Full Mermaid diagrams (all ORM tables, cascade notes, AGE vs `memory_graph`): [er-diagram.md](er-diagram.md).

## Retention

Session-scoped purge: [retention-policy.md](retention-policy.md) and `scripts/db/retention_batch.py`.
