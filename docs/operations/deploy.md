# Deploy Operations

Version: 0.1 (P2-B skeleton)

## Overview

Secrets for Docker Compose and `vita-api` no longer live in `docker-compose.yml`. They are supplied via:

| Context | Source |
|---------|--------|
| Local dev | `config/.env.compose` (gitignored, copy from `config/.env.compose.example`) |
| CI validation | `config/.env.compose.ci` (synthetic, committed) |
| Staging / production | GitHub Encrypted Secrets, materialized at deploy time |

Application code on the host reads DB credentials through `compose_env.py` -> `app/config.py` (same keys as compose env file).

## Local setup

```powershell
Copy-Item config\.env.compose.example config\.env.compose
# Edit config/.env.compose — set POSTGRES_PASSWORD and app secrets.

docker compose --env-file config/.env.compose up -d postgres
python scripts/dev/verify_platform_postgres.py
```

If you already have a Postgres volume created with password `0000`, set `POSTGRES_PASSWORD=0000` and matching `DATABASE_URL` in `config/.env.compose` (do not commit that file).

## GitHub Actions: Deploy workflow

Workflow: `.github/workflows/deploy.yml`

- Trigger: **workflow_dispatch** (manual)
- Input `dry_run` (default `true`): validates compose only
- Input `environment`: `staging` or `production` (uses GitHub Environment for optional approval gates)

### Required repository / environment secrets

Configure under **Settings -> Secrets and variables -> Actions** (or per-environment secrets):

| Secret | Purpose |
|--------|---------|
| `POSTGRES_USER` | Postgres role |
| `POSTGRES_PASSWORD` | Postgres password |
| `POSTGRES_DB` | Database name |
| `DB_USER` | App DB user (usually same as POSTGRES_USER) |
| `DB_PASSWORD` | App DB password |
| `DB_HOST` | Hostname inside compose network (typically `postgres`) |
| `DB_PORT` | Port (typically `5432`) |
| `DB_NAME` | Database name |
| `DATABASE_URL` | SQLAlchemy URL for vita-api |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin |
| `N8N_BASIC_AUTH_USER` | n8n basic auth user |
| `N8N_BASIC_AUTH_PASSWORD` | n8n basic auth password |
| `N8N_ENCRYPTION_KEY` | n8n credential encryption (min 32 chars) |
| `JWT_SECRET` | vita-api JWT signing |
| `ENCRYPT_KEY` | Field encryption |
| `SECRET_KEY` | Session / general secret |
| `API_KEY` | API authentication |

Materialization script (never logs values):

```bash
python scripts/deploy/write_compose_env.py --from-env --require-all
docker compose --env-file config/.env.compose config --quiet
```

## Rollback (skeleton)

1. Restore previous container image tag or compose revision.
2. Restore prior secret snapshot (environment-specific backup of `config/.env.compose` on the host, not in git).
3. `docker compose --env-file config/.env.compose up -d` with previous env file.
4. Run smoke: `curl -f http://localhost:8080/health` and `python scripts/dev/verify_platform_postgres.py`.

Full CD (build, push, automated smoke, blue/green) is out of scope for P2-B.

## Related

- [../security/secrets-policy.md](../security/secrets-policy.md)
- [../governance/tech-debt-register.md](../governance/tech-debt-register.md) (TD-006)
