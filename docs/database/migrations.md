# Database migrations (Alembic)

P2 introduces versioned ORM migrations alongside existing SQL bootstrap.

## Responsibilities

| Layer | Owner | Purpose |
|-------|-------|---------|
| `init-db/*.sql` | Docker first boot | Extensions (vector, age, pg_cron), HNSW, AGE graph, pg_cron jobs |
| `db_manager` bootstrap | App startup | Idempotent ensure (extensions, graph, indexes, seed data) |
| `alembic/versions/` | Alembic | Versioned DDL for SQLAlchemy models in `db_manager.py` |

## Commands

```powershell
# Show current revision
alembic current

# Apply pending migrations
alembic upgrade head

# Autogenerate from ORM changes (review before commit)
alembic revision --autogenerate -m "describe change"
```

Database URL is read from `app.config` (`.env.local` host settings + `config/.env.compose` credentials via compose_env).

## Baseline

Revision `20260702_0001` is a no-op stamp. Existing databases created via init-db + db_manager are already at this baseline; run `alembic stamp head` once on existing deployments before applying new revisions.

## Local Platform Postgres

Extensions require `vita-postgres:pg16-vector-age-cron`:

```powershell
Copy-Item config\.env.compose.example config\.env.compose
docker compose --env-file config/.env.compose up -d postgres
python scripts/dev/verify_platform_postgres.py
```
