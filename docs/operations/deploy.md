# Deploy Operations

Version: 0.2 (P3-5 build + smoke + SSH deploy)

## Overview

Secrets for Docker Compose and `vita-api` no longer live in `docker-compose.yml`. They are supplied via:

| Context | Source |
|---------|--------|
| Local dev | `config/.env.compose` (gitignored, copy from `config/.env.compose.example`) |
| CI / deploy dry-run smoke | `config/.env.compose.ci` (synthetic, committed) |
| Staging / production | GitHub Encrypted Secrets, materialized at deploy time |

Application code on the host reads DB credentials through `compose_env.py` -> `app/config.py` (same keys as compose env file).

## Local setup

```powershell
Copy-Item config\.env.compose.example config\.env.compose
# Edit config/.env.compose — set POSTGRES_PASSWORD and app secrets.

docker compose --env-file config/.env.compose build postgres
docker compose --env-file config/.env.compose up -d postgres redis
python scripts/dev/verify_platform_postgres.py
```

Build and smoke locally (minimal stack):

```powershell
docker build -t vita-api:local .
$env:VITA_API_IMAGE = "vita-api:local"
docker compose --env-file config/.env.compose.ci -f docker-compose.yml -f docker-compose.smoke.yml up -d postgres redis vita-api --build
bash scripts/deploy/smoke_check.sh
docker compose --env-file config/.env.compose.ci -f docker-compose.yml -f docker-compose.smoke.yml down -v
```

## Troubleshooting

### Redis unhealthy / `Bad file format reading the append only file`

Dev `redis_data` volume AOF can corrupt after unclean shutdown. Smoke uses **`redis_smoke_data`** (see `docker-compose.smoke.yml`) to avoid that; always pass both compose files for smoke.

Recovery for full dev stack:

```powershell
docker compose --env-file config/.env.compose down
docker volume rm engine7b_redis_data
docker compose --env-file config/.env.compose up -d redis
```

Volume name prefix matches the project directory (`engine7b_redis_data` when run from `engine7b`).

### vita-api unhealthy / `Invalid JWT_SECRET for production`

The image must not include `config/.env.local` (see `.dockerignore`). Smoke sets `ENV=testing` and passes secrets from `--env-file`.

Rebuild after pulling fixes:

```powershell
docker build -t vita-api:local .
docker compose --env-file config/.env.compose.ci -f docker-compose.yml -f docker-compose.smoke.yml up -d postgres redis vita-api --no-build --force-recreate
bash scripts/deploy/smoke_check.sh
```

`status=degraded` on `/health` is expected when LLM hosts are offline; smoke only requires HTTP 200 and `vita_crisis` in `/metrics`.

### `POSTGRES_USER is required` on compose commands

Always pass `--env-file config/.env.compose` or `config/.env.compose.ci`:

```powershell
docker compose --env-file config/.env.compose.ci logs redis
```

## GitHub Actions: Deploy workflow

Workflow: `.github/workflows/deploy.yml`

| Input | Default | Meaning |
|-------|---------|---------|
| `environment` | `staging` | GitHub Environment (optional approval gates) |
| `dry_run` | `true` | Build + runner smoke only; skip SSH host deploy |

### Jobs

1. **build-and-smoke** — builds `vita-postgres` + `vita-api:${{ github.sha }}`, starts `postgres` / `redis` / `vita-api`, runs `scripts/deploy/smoke_check.sh`.
2. **deploy-host** (only when `dry_run=false`) — materializes secrets, streams Docker image to host via SSH, runs remote `docker compose up` + smoke.

### Verified Actions (security)

Only official `actions/*` with pinned tags:

- `actions/checkout@v4`

No third-party Marketplace actions. No secret literals in YAML.

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
| `JWT_SECRET` | vita-api JWT signing (min 32 chars, not `dev_`) |
| `ENCRYPT_KEY` | Field encryption |
| `SECRET_KEY` | Session / general secret |
| `API_KEY` | API authentication (min 32 chars) |

Host deploy (when `dry_run=false`):

| Secret | Purpose |
|--------|---------|
| `DEPLOY_HOST` | Target server hostname or IP |
| `DEPLOY_KEY` | SSH private key (PEM, full key body) |
| `DEPLOY_USER` | SSH user (optional, default `deploy`) |
| `DEPLOY_PATH` | Repo root on host (optional, default `/opt/vita`) |

The deploy host must contain a git checkout of this repository (including `scripts/deploy/smoke_check.sh` and compose files).

Materialization (never logs values):

```bash
python scripts/deploy/write_compose_env.py --from-env --require-all
docker compose --env-file config/.env.compose config --quiet
```

### Smoke checks

Script: `scripts/deploy/smoke_check.sh`

- `GET /health` returns HTTP 200
- `GET /metrics` contains `vita_crisis` Prometheus series

Environment variables:

| Variable | Default |
|----------|---------|
| `SMOKE_BASE_URL` | `http://localhost:8080` |
| `SMOKE_MAX_WAIT_SEC` | `180` |

## Rollback

On the deploy host (after taking a backup of `config/.env.compose`):

```bash
export PREVIOUS_IMAGE_TAG=<git-sha-or-tag>
bash scripts/deploy/rollback.sh
```

Steps performed:

1. Restore `config/.env.compose.backup` if present.
2. Retag / pull `vita-api:${PREVIOUS_IMAGE_TAG}` as `vita-api:latest`.
3. `docker compose up -d vita-api --no-build`.
4. Run smoke checks.

## Docker image notes

- `Dockerfile` uses `requirements-docker.txt` (no llama-cpp build; LLM inference runs on Compute Engine host).
- Root modules `compose_env.py`, `hardware_profile_loader.py`, `vita_core_config.py` are copied into the image (required by `app/config.py` and `app/main.py`).
- `dict/` (rime-cantonese) is **not** in git; the image creates an empty `/app/dict`. Mount host data for full Cantonese dictionary lookup:

```yaml
# optional in docker-compose override
volumes:
  - ./dict:/app/dict:ro
```

## Related

- [../security/secrets-policy.md](../security/secrets-policy.md)
- [../governance/tech-debt-register.md](../governance/tech-debt-register.md) (TD-006 closed P2-B)
- [../governance/execution-program.md](../governance/execution-program.md) (P3-5)
