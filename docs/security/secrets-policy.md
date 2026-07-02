# Secrets Policy

Version: 0.2 (P2-B)

## Single source of truth

| Secret type | Authoritative location | Application read path |
|-------------|------------------------|------------------------|
| Compose stack secrets (Postgres, Grafana, n8n, vita-api) | `config/.env.compose` (local, gitignored) or GitHub Encrypted Secrets (deploy) | `docker compose --env-file`; `compose_env.py` -> `app/config.py` |
| JWT / ENCRYPT / SECRET / API keys (host dev) | Environment variables or `config/.env.local` (non-DB only) | `app/config.py` |
| GitHub deploy tokens | GitHub Encrypted Secrets | `.github/workflows/deploy.yml` |

**Rule**: Do not commit literal production passwords in `docker-compose.yml`, `.py`, committed `.env` files, or workflow YAML.

`docker-compose.yml` uses `${VAR:?message}` interpolation only; values come from `config/.env.compose` or CI file `config/.env.compose.ci`.

## Development vs production

- Copy `config/.env.compose.example` to `config/.env.compose` for local Docker.
- `config/.env.local` must not contain `DB_PASSWORD` or full `DATABASE_URL` with embedded password (use `compose_env.py`).
- Production/staging: `config.validate()` rejects `JWT_SECRET`, `ENCRYPT_KEY`, `SECRET_KEY` starting with `dev_` or shorter than 32 characters.

## CI/CD rules

1. Only Verified Creator GitHub Actions (`actions/*` with blue badge).
2. Pin version tags (`@v4`, `@v5`), never `@main`.
3. No secrets in `.github/workflows/*.yml` — use repository Settings -> Secrets and variables -> Actions.
4. `permissions: contents: read` default unless a job explicitly needs more.
5. CI compose validation: `docker compose --env-file config/.env.compose.ci config --quiet`.

## Rotation

| Secret | Recommended cadence | Procedure |
|--------|---------------------|-----------|
| DB password | On compromise or annual | Update GitHub Secret / `config/.env.compose`; alter Postgres role; restart services |
| JWT_SECRET | On compromise or 90 days | Rotate in env; invalidate outstanding tokens |
| API_KEY | On compromise | Regenerate; update client integrations |

Document rotation in incident report ([../operations/incident.md](../operations/incident.md)).

## Logging

- Never log full DATABASE_URL with password (config masks in startup logs).
- `scripts/deploy/write_compose_env.py` must not print secret values.
- Private and crisis content: see [session-isolation.md](session-isolation.md).

## Prohibited

- Hard-coded hotline or credentials in user-facing strings (see companion language policy)
- Committing `config/.env.compose` or `.env.local` with production secrets
- Third-party unverified GitHub Actions handling repository checkout or secrets
