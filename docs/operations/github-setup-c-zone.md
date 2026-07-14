# GitHub Setup — C Zone (Branch Protection + Encrypted Secrets)

Version: 1.0  
Date: 2026-07-08  
Repo: `Raven777494/vita_jul2026`  
Aligns: [go-live-checklist.md](../governance/go-live-checklist.md) items **0.2** and **1.1**

## Security principles (mandatory)

| # | Rule | VITA implementation |
|---|------|---------------------|
| 1 | **Verified Creator only** — blue checkmark on GitHub Marketplace | Workflows use **only** `actions/checkout`, `actions/setup-python` (official `actions/*` org). No third-party Marketplace actions. |
| 2 | **Pin versions** — never `@main` / `@master` | `actions/checkout@v4`, `actions/setup-python@v5`. Verified in CI by `verify_github_workflows.py`. |
| 3 | **Encrypted Secrets** — no passwords in YAML | Deploy uses `${{ secrets.NAME }}` only. `scan_secrets.py` + `verify_deploy_secrets_contract.py` in CI. |

Local verify (before changing GitHub settings):

```powershell
python scripts/governance/verify_github_workflows.py
python scripts/governance/verify_deploy_secrets_contract.py
python scripts/security/scan_secrets.py
```

---

## C1 — Branch protection (go-live 0.2)

**Owner (A):** ENG  
**Where:** GitHub -> Settings -> Branches -> Add branch protection rule

Apply **two rules** (one per branch): `main` and `develop`.

### Recommended settings

| Setting | `main` | `develop` |
|---------|--------|-----------|
| Require a pull request before merging | Yes | Yes |
| Required approvals | 1 (or 0 if solo maintainer — document in external ops log) | Same |
| Dismiss stale pull request approvals | Yes | Yes |
| Require status checks to pass | Yes | Yes |
| Require branches to be up to date | Yes | Yes |
| Status checks required | See below | See below |
| Require conversation resolution | Yes | Yes |
| Include administrators | Yes (recommended) | Yes |
| Allow force pushes | **No** | **No** |
| Allow deletions | **No** | **No** |

### Required status checks

After at least one green CI run on the branch, add these checks (names match workflow **job** ids):

| Check name | Workflow | Job |
|------------|----------|-----|
| `test-and-alignment` | CI | test-and-alignment |
| `dependency-audit` | CI | dependency-audit |

If GitHub UI shows prefixed names (e.g. `CI / test-and-alignment`), select the entries that correspond to the jobs above.

### Acceptance record

Store externally (ops log, not in repo):

| Field | Value |
|-------|-------|
| Record ID | BP-RECORD-2026-07-NNN |
| Date | |
| Branches protected | main, develop |
| Screenshot / export | Settings -> Branches |
| Verified by | ENG |

Update [go-live-checklist.md](../governance/go-live-checklist.md) item **0.2** when complete.

---

## C2 — Encrypted Secrets (go-live 1.1)

**Owner (A):** ENG / OPS  
**Where:** GitHub -> Settings -> Secrets and variables -> Actions

### Repository secrets (smoke + compose materialization)

Required for `deploy.yml` when `dry_run=false` or when using `write_compose_env.py --require-all`:

| Secret | Min length / notes |
|--------|-------------------|
| `POSTGRES_USER` | e.g. `postgres` |
| `POSTGRES_PASSWORD` | strong random |
| `POSTGRES_DB` | e.g. `vita_db` |
| `DB_USER` | usually same as POSTGRES_USER |
| `DB_PASSWORD` | same as POSTGRES_PASSWORD or app-specific |
| `DB_HOST` | `postgres` (compose network) |
| `DB_PORT` | `5432` |
| `DB_NAME` | same as POSTGRES_DB |
| `DATABASE_URL` | `postgresql+psycopg2://...` (or leave unset; script builds from parts) |
| `GRAFANA_ADMIN_PASSWORD` | strong random |
| `N8N_BASIC_AUTH_USER` | non-default |
| `N8N_BASIC_AUTH_PASSWORD` | strong random |
| `N8N_ENCRYPTION_KEY` | **>= 32 chars** |
| `JWT_SECRET` | **>= 32 chars**, not `dev_` prefix |
| `ENCRYPT_KEY` | strong random |
| `SECRET_KEY` | strong random |
| `API_KEY` | **>= 32 chars**, not `dev_` prefix |

### Host deploy secrets (`dry_run=false` only)

| Secret | Purpose |
|--------|---------|
| `DEPLOY_HOST` | Staging/production server hostname or IP |
| `DEPLOY_KEY` | SSH private key (PEM, full body including headers) |
| `DEPLOY_USER` | SSH user (optional; default `deploy`) |
| `DEPLOY_PATH` | Repo path on host (optional; default `/opt/vita`) |

### Environment secrets (recommended)

Create GitHub **Environments** `staging` and `production`:

Settings -> Environments -> New environment

| Environment | Protection rules (recommended) |
|-------------|-------------------------------|
| `staging` | Optional: required reviewers (ENG) |
| `production` | Required reviewers (ENG + OPS); deployment branch `main` only |

Copy the same secret **names** into each environment with environment-specific values.  
`deploy.yml` uses `environment: ${{ inputs.environment }}` so staging deploy reads `staging` secrets.

### Generate local values (do not commit)

```powershell
# Example: generate URL-safe secrets locally, paste into GitHub UI only
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Never paste generated values into tracked files. Use GitHub UI or `gh secret set` from a trusted machine.

### Acceptance record

| Field | Value |
|-------|-------|
| Record ID | SEC-RECORD-2026-07-NNN |
| Date | |
| Secrets configured | repo and/or staging environment |
| Names verified | `python scripts/governance/verify_deploy_secrets_contract.py` |
| Verified by | ENG |

Update [go-live-checklist.md](../governance/go-live-checklist.md) item **1.1** when complete.

---

## C2 step-by-step verification checklist

Use this when configuring secrets before **D2** (`dry_run=false`).  
Repo-side name contract (no values): `python scripts/governance/verify_deploy_secrets_contract.py`

**Important:** D1 (`dry_run=true`) does **not** need these secrets — it uses `config/.env.compose.ci`.  
Deploy #7 failed because `dry_run=false` was selected without secrets configured.

### Step 0 — Choose secret scope

| Scope | Where | When to use |
|-------|-------|-------------|
| **Recommended** | Settings -> Environments -> **staging** | D2 staging deploy (`deploy.yml` reads `environment: staging`) |
| Optional fallback | Settings -> Secrets and variables -> Actions -> **Repository secrets** | Only if not using environment-scoped secrets |

Create environment **staging** first:

1. GitHub repo -> **Settings**
2. **Environments** -> **New environment** -> name: `staging`
3. (Optional) Add required reviewers: ENG

### Step 1 — Compose secrets (17 names, required for D2)

Add each secret under **staging** environment (or repository secrets).  
Check off in GitHub UI as you add each name.

| # | Secret name | Example / constraint | Required for D2 |
|---|-------------|----------------------|-----------------|
| 1 | `POSTGRES_USER` | `postgres` | Yes |
| 2 | `POSTGRES_PASSWORD` | strong random (>= 16 chars) | Yes |
| 3 | `POSTGRES_DB` | `vita_db` | Yes |
| 4 | `DB_USER` | same as `POSTGRES_USER` | Yes |
| 5 | `DB_PASSWORD` | same as `POSTGRES_PASSWORD` or app-specific | Yes |
| 6 | `DB_HOST` | `postgres` (compose service name) | Yes |
| 7 | `DB_PORT` | `5432` | Yes |
| 8 | `DB_NAME` | same as `POSTGRES_DB` | Yes |
| 9 | `DATABASE_URL` | `postgresql+psycopg2://user:pass@postgres:5432/vita_db` **or omit** if rows 4–8 set | Optional* |
| 10 | `GRAFANA_ADMIN_PASSWORD` | strong random | Yes |
| 11 | `N8N_BASIC_AUTH_USER` | non-default (not `admin` in production) | Yes |
| 12 | `N8N_BASIC_AUTH_PASSWORD` | strong random | Yes |
| 13 | `N8N_ENCRYPTION_KEY` | **>= 32 characters** | Yes |
| 14 | `JWT_SECRET` | **>= 32 chars**, must not start with `dev_` | Yes |
| 15 | `ENCRYPT_KEY` | strong random | Yes |
| 16 | `SECRET_KEY` | strong random | Yes |
| 17 | `API_KEY` | **>= 32 chars**, must not start with `dev_` | Yes |

\* `write_compose_env.py --require-all` auto-builds `DATABASE_URL` when DB parts (rows 4–8) are present.

Generate values locally (paste into GitHub UI only — never commit):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 2 — Host deploy secrets (4 names, required for D2 deploy-host job)

| # | Secret name | Format | Required for D2 |
|---|-------------|--------|-----------------|
| 18 | `DEPLOY_HOST` | staging server hostname or IP | Yes |
| 19 | `DEPLOY_KEY` | full SSH private key PEM (`-----BEGIN ... KEY-----`) | Yes |
| 20 | `DEPLOY_USER` | SSH user (default `deploy` if omitted in workflow) | Recommended |
| 21 | `DEPLOY_PATH` | repo path on host (default `/opt/vita`) | Recommended |

Host must have git checkout at `DEPLOY_PATH` (see [deploy-d-zone.md](deploy-d-zone.md) bootstrap).

### Step 3 — Verify in GitHub UI

1. Settings -> Environments -> **staging** -> Environment secrets
2. Confirm **21 secret names** exist (or 20 if skipping optional `DEPLOY_USER` / `DEPLOY_PATH` — workflow defaults apply)
3. Confirm names match **exactly** (case-sensitive, underscores)

### Step 4 — Verify from repo (names only)

```powershell
python scripts/governance/verify_deploy_secrets_contract.py
python scripts/governance/verify_staging_secrets_presence.py
python scripts/security/scan_secrets.py
```

`verify_staging_secrets_presence.py` requires authenticated `gh` CLI; it checks **names only**, never values.
`DATABASE_URL` is **optional** when `DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`/`DB_NAME` (or `POSTGRES_*` equivalents) are present — matches `write_compose_env.py --require-all`.
If `gh` is unavailable, use the printed manual checklist (exit code 2).

Both contract verifiers must print `[OK]`.

### Step 5 — Functional verify (D2 dry run on GHA)

Only after Steps 1–4:

1. Actions -> Deploy -> Run workflow
2. Branch: `develop`
3. `environment` = **staging**
4. **Uncheck** Runner smoke only (`dry_run=false`)
5. Expected: **Build and smoke** green, then **Deploy to host** green

If Step 5 fails with `Missing required environment variables`, return to Step 1 — a compose secret name is missing or empty in the **staging** environment (not repository-level only).

### Step 6 — External acceptance record

| Field | Value |
|-------|-------|
| Record ID | SEC-RECORD-2026-07-NNN |
| Date | |
| Scope | staging environment secrets |
| Count | 17 compose + 4 host (or 21 total) |
| Verified by | ENG / OPS |
| D2 run URL | (after Step 5 green) |

Mark [go-live-checklist.md](../governance/go-live-checklist.md) item **1.1** complete when Step 6 is filed.

---

## Optional: `gh` CLI (after install)

```powershell
gh auth login
gh secret set POSTGRES_PASSWORD --body "..." --repo Raven777494/vita_jul2026
gh secret set API_KEY --env staging --body "..."
```

Branch protection via API requires admin scope; prefer UI for first setup, then export settings to ops log.

---

## Related

- [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
- [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml)
- [deploy.md](deploy.md)
- [branch-strategy.md](../governance/branch-strategy.md)
- [secrets-policy.md](../security/secrets-policy.md)
