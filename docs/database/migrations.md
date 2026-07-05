# Database migrations (Alembic)

Version: 0.2 (P4-1)

Alembic is the **primary** path for relational DDL changes to SQLAlchemy models in `app/services/db_manager.py`.

## Responsibility split

| Layer | Owner | Purpose | New changes |
|-------|-------|---------|-------------|
| `alembic/versions/` | Alembic | Versioned DDL for ORM tables | **Required** for column/table/index changes |
| `init-db/*.sql` | Docker first boot | Extensions (vector, age, pg_cron), HNSW, AGE graph, pg_cron jobs | Extensions and platform objects only |
| `db_manager` bootstrap | App startup | Idempotent ensure (extensions, graph, indexes, seed data) | Safety net only; do not add new schema here |

### Policy (P4-1)

1. Every ORM schema change starts with `alembic revision --autogenerate -m "describe change"`, manual review, then commit.
2. Do not add new `CREATE TABLE` / `ALTER TABLE` for ORM entities in `init-db/` or bootstrap helpers.
3. `init-db/` remains limited to PostgreSQL extensions, HNSW, Apache AGE graph shell (read-only reserve per [ADR-002](../architecture/adr-002-memory-model.md)), and pg_cron schedules.
4. Bootstrap code may create missing indexes or extension objects idempotently, but must not diverge from the latest Alembic head.
5. If drift is found between a live database and ORM models, add a corrective Alembic revision rather than patching SQL bootstrap files.

## Commands

```powershell
# Show current revision
alembic current

# Apply pending migrations
alembic upgrade head

# Stamp an existing DB that was bootstrapped before Alembic (one-time)
alembic stamp head

# Autogenerate from ORM changes (review before commit)
alembic revision --autogenerate -m "describe change"
```

Database URL is read from `app.config` (`.env.local` host settings + `config/.env.compose` credentials via `compose_env`).

## Baseline

Revision `20260702_0001` is a no-op stamp representing the schema created by historical init-db + db_manager bootstrap.

| Database state | Action |
|----------------|--------|
| Fresh install (init-db + app bootstrap) | `alembic stamp head` after first boot, then `alembic upgrade head` for future revisions |
| Existing deployment (pre-Alembic) | One-time `alembic stamp head`, verify `alembic current`, then `alembic upgrade head` on deploy |
| CI / local dev | Postgres via compose; stamp once per volume if `alembic_version` missing |

No corrective drift revision is required at P4-1 baseline: ORM matches init-db bootstrap. Future model edits must ship as new revisions.

## Developer workflow checklist

1. Edit SQLAlchemy model in `app/services/db_manager.py`.
2. `alembic revision --autogenerate -m "..."` — inspect generated SQL; remove unrelated autogen noise.
3. Apply locally: `alembic upgrade head`.
4. Run app tests and `python scripts/dev/verify_platform_postgres.py`.
5. Update [er-diagram.md](er-diagram.md) if relationships or tables changed.

## Local Platform Postgres

Extensions require `vita-postgres:pg16-vector-age-cron`:

```powershell
Copy-Item config\.env.compose.example config\.env.compose
docker compose --env-file config/.env.compose up -d postgres
python scripts/dev/verify_platform_postgres.py
alembic current
```

## Related

- [er-diagram.md](er-diagram.md)
- [schema-overview.md](schema-overview.md)
- TD-002 closed at P4-1 (Alembic primary policy)
