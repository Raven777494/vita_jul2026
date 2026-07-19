# Staging Deploy and Monitoring — D Zone

Version: 1.0  
Date: 2026-07-08  
Repo: `Raven777494/vita_jul2026`  
Release tag: `v1.0.0-rc.2` (C-zone baseline)  
Aligns: [go-live-checklist.md](../governance/go-live-checklist.md) items **1.2–1.4** and **2.1–2.4**

## Prerequisites

Complete [github-setup-c-zone.md](github-setup-c-zone.md) first:

| Prerequisite | Checklist | Required before |
|--------------|-----------|-----------------|
| GitHub Encrypted Secrets (staging environment) | 1.1 | D1 (`dry_run=true` with real secrets optional; uses `.env.compose.ci` when `dry_run=true`) |
| `DEPLOY_HOST` + `DEPLOY_KEY` (+ optional `DEPLOY_USER`, `DEPLOY_PATH`) | 1.1 | D2 (`dry_run=false`) |
| Staging host git checkout at `DEPLOY_PATH` | — | D2, D3 |

Local repo verification (run before any GHA deploy):

```powershell
python scripts/governance/verify_deploy_d_zone.py
python scripts/governance/verify_github_workflows.py
python scripts/governance/verify_deploy_secrets_contract.py
python scripts/security/scan_secrets.py
```

---

## Staging host bootstrap (one-time)

On the deploy host (`DEPLOY_PATH`, default `/opt/vita`):

```bash
git clone https://github.com/Raven777494/vita_jul2026.git /opt/vita
cd /opt/vita
git checkout develop
# config/.env.compose is written by deploy workflow — do not commit secrets on host
```

Host requirements:

- Docker Engine + Docker Compose v2 plugin
- SSH access for deploy user (key in `DEPLOY_KEY` secret)
- Outbound internet for Docker base images (first postgres build)

---

## D1 — Runner smoke deploy (go-live 1.2)

**Owner (A):** OPS  
**Executor (R):** ENG  
**Goal:** Confirm GitHub Actions **build-and-smoke** job green on staging environment.

### Steps

1. Open **Actions -> Deploy -> Run workflow**
2. Branch: `develop`
3. Inputs:
   - `environment` = **staging**
   - `dry_run` = **true**
4. Confirm job **Build and smoke** completes:
   - Builds `vita-postgres` + `vita-api:${{ github.sha }}`
   - Starts postgres / redis / vita-api (smoke override)
   - Runs `scripts/deploy/smoke_check.sh`
5. Save workflow run URL for ops record

### Acceptance

| Field | Value |
|-------|-------|
| Checklist item | 1.2 |
| Job required green | `Build and smoke` |
| deploy-host job | skipped (`dry_run=true`) |
| Record ID | DEP-DRILL-YYYY-MM-NNN (step 1 of drill) |

**Completed example (2026-07-08):** Deploy workflow run **#8** on `develop` @ `c6888b6` — build-and-smoke 2m 1s green; deploy-host skipped.

Update [go-live-checklist.md](../governance/go-live-checklist.md) item **1.2** when complete.

---

## D2 — Staging host deploy (go-live 1.3)

**Owner (A):** OPS  
**Executor (R):** ENG  
**Goal:** End-to-end deploy to staging host via SSH.

### Steps

1. Confirm staging **Environment secrets** include all compose keys (see [github-setup-c-zone.md](github-setup-c-zone.md) C2) plus `DEPLOY_*` host secrets.
2. Run workflow:
   - `environment` = **staging**
   - `dry_run` = **false**
3. Confirm both jobs green:
   - **Build and smoke** (runner pre-check)
   - **Deploy to host** (SSH image stream + remote compose)
4. On host (optional manual verify):

```bash
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/metrics | grep vita_crisis
```

Remote deploy script backs up `config/.env.compose` to `.env.compose.backup` before replace (rollback support).

### Acceptance (GHA D2)

| Field | Value |
|-------|-------|
| Checklist item | 1.3 |
| Jobs required green | `Build and smoke`, `Deploy to host` |
| Image tag | `vita-api:<github.sha>` |
| Smoke | pass on host |

### D2-B — HSS local deploy (go-live 1.3, solo-operator)

Use when staging is **local HSS** (`D:\vita`) and GHA SSH deploy is not configured.
Acceptance equivalent to D2 for checklist **1.3** when documented as D2-B.

**Prerequisites**

- `config/.env.compose` exists on HSS (not `.env.compose.ci`)
- Docker Desktop running
- `bash` available (Git Bash / WSL)

**Steps**

```powershell
cd D:\vita
.\scripts\deploy\hss_local_deploy.ps1 -IncludeMonitoring
```

Optional flags:

| Flag | Purpose |
|------|---------|
| `-SkipPull` | Skip `git pull` (already synced) |
| `-SkipBuild` | Reuse existing images |
| `-ImageTag local` | Tag built image as `vita-api:local` |
| `-IncludeMonitoring` | Also start victorialogs, vmsingle, grafana |

**Expected**

```
[DEPLOY] git pull origin develop
[DEPLOY] backed up config\.env.compose
[DEPLOY] docker compose build postgres
[DEPLOY] docker build vita-api:latest
[DEPLOY] docker compose up -d postgres, redis, vita-api, ...
[SMOKE] Health endpoint reachable ...
[OK] Smoke checks passed ...
[OK] HSS local deploy complete (vita-api:latest @ <sha>)
```

Post-deploy verify:

```powershell
python scripts/observability/verify_p5_monitoring.py
```

**Acceptance record**

| Field | Value |
|-------|-------|
| Checklist item | 1.3 (D2-B path) |
| Record ID | DEP-DRILL-YYYY-MM-NNN |
| Commit SHA | from script output |
| Smoke | `[OK] Smoke checks passed` |

GHA D2 (`dry_run=false`) remains optional when SSH host deploy is configured per C2.

---

## D3 — Rollback drill (go-live 1.4)

**Owner (A):** OPS  
**Executor (R):** ENG  
**Goal:** Restore previous `vita-api` image after a failed or superseded deploy.

### D3-A — HSS local drill (no GHA; checklist 1.4)

Use when HSS is already live at `D:\vita` (or Linux `${DEPLOY_PATH}`) without D2 GHA deploy.

**Prerequisites**

- `config/.env.compose` exists (not `.env.compose.ci` for monitoring stack)
- `postgres` + `redis` healthy (`docker compose ps`)
- `bash` available (`C:\Windows\System32\bash.exe` on Windows)
- Two local image tags to simulate before/after deploy

**Step 0 — Sync repo (engine7b -> HSS)**

```powershell
# After pulling develop in D:\Desktop\engine7b, copy or git pull in D:\vita
cd D:\vita
git pull origin develop
```

**Step 1 — Ensure monitoring stack up**

```powershell
cd D:\vita
docker compose --env-file config\.env.compose up -d postgres redis vita-api
docker compose --env-file config\.env.compose ps
```

**Step 2 — Create drill image tags (simulate deploy versions)**

```powershell
# Tag current known-good image as "before"
docker tag vita-api:local vita-api:drill-before

# Simulate a new deploy build (or retag for drill-only)
docker build -t vita-api:drill-after .
# Drill-only shortcut (same layers): docker tag vita-api:local vita-api:drill-after
```

**Step 3 — Simulate superseding deploy (switch to drill-after)**

```powershell
docker tag vita-api:drill-after vita-api:latest
docker compose --env-file config\.env.compose up -d vita-api --no-build --wait
bash scripts/deploy/smoke_check.sh
```

**Step 4 — Backup compose env (simulates D2 remote backup)**

```powershell
Copy-Item config\.env.compose config\.env.compose.backup -Force
```

**Step 5 — Execute rollback**

```powershell
# PowerShell (preferred on HSS)
.\scripts\deploy\rollback.ps1 -PreviousImageTag drill-before
```

Or manually:

```powershell
# PowerShell
$env:PREVIOUS_IMAGE_TAG = "drill-before"
# Clear stale override if set from earlier smoke sessions
Remove-Item Env:\VITA_API_IMAGE -ErrorAction SilentlyContinue
bash scripts/deploy/rollback.sh
```

Do **not** use CMD `set` + manual `docker tag` only — that skips backup restore and script validation.

Git Bash alternative:

```bash
export PREVIOUS_IMAGE_TAG=drill-before
unset VITA_API_IMAGE
bash scripts/deploy/rollback.sh
```

**Expected output**

```
[ROLLBACK] Tagging vita-api:drill-before as vita-api:latest
[ROLLBACK] Recreating vita-api via compose
[SMOKE] Health endpoint reachable ...
[OK] Smoke checks passed ...
[OK] Rollback complete (vita-api -> drill-before)
```

**Step 6 — Verify image tag**

```powershell
docker inspect vita-api --format "{{.Config.Image}}"
docker images vita-api
```

**Step 7 — External record (checklist 1.4)**

| Field | Example |
|-------|---------|
| Drill ID | DEP-DRILL-2026-07-003 |
| Environment | HSS `D:\vita` local |
| Deploy workflow run URL | n/a (local drill) |
| Image tag deployed | `vita-api:drill-after` |
| Rollback tag | `drill-before` |
| Rollback smoke result | pass |

### D3-B — Post-D2 rollback (GHA deploy host)

On the **deploy host** after D2 succeeded at least once:

```bash
cd "${DEPLOY_PATH:-/opt/vita}"
export PREVIOUS_IMAGE_TAG=<known-good-git-sha>
bash scripts/deploy/rollback.sh
```

`rollback.sh`:

1. Restores `config/.env.compose.backup` if present
2. Retags `vita-api:${PREVIOUS_IMAGE_TAG}` as `vita-api:latest`
3. Sets `VITA_API_IMAGE=vita-api:latest` (avoids stale shell override)
4. Recreates `vita-api` via compose with `--wait`
5. Runs `smoke_check.sh`

Smoke-stack hosts only: pass extra compose file:

```bash
export COMPOSE_EXTRA_FILES="-f docker-compose.smoke.yml"
export PREVIOUS_IMAGE_TAG=<sha>
bash scripts/deploy/rollback.sh
```

### Drill record template

Store in external ops storage (see [deploy.md](deploy.md) appendix). Minimum fields:

| Field | Value |
|-------|-------|
| Drill ID | DEP-DRILL-YYYY-MM-NNN |
| Date (UTC) | |
| Operator | |
| Environment | staging |
| Deploy workflow run URL (D1/D2) | |
| Image tag deployed | |
| Smoke result | pass / fail |
| Rollback performed | yes |
| Rollback tag (`PREVIOUS_IMAGE_TAG`) | |
| Rollback smoke result | pass / fail |
| Notes | |

Update [go-live-checklist.md](../governance/go-live-checklist.md) items **1.4** when complete.

---

## D4 — Staging monitoring live (go-live 2.1–2.4)

**Owner (A):** OPS  
**Executor (R):** ENG  
**Goal:** Observability stack UP, clinical alert fire, webhook drill, steady-state check.

After D2, on staging host (full observability stack):

```bash
cd "${DEPLOY_PATH:-/opt/vita}"
python scripts/observability/render_grafana_alert_contact.py
docker compose --env-file config/.env.compose up -d victorialogs vmsingle grafana vita-api
python scripts/observability/verify_p5_monitoring.py
```

### Checklist mapping

| Item | Action | Evidence |
|------|--------|----------|
| **2.1** Grafana / VM / `/metrics` UP | `verify_p5_monitoring.py` all checks green | scrape targets UP screenshot |
| **2.2** Clinical alert fire test | Inject missed interception log per [monitoring.md](monitoring.md) | alert firing screenshot + LogsQL |
| **2.3** Escalation webhook live | `drill_escalation_webhook.py` live or `--local-capture` (see D4-B) | `WEBHOOK-DRILL-*` proof JSONL |
| **2.4** Steady-state 7 days | Daily `record_mon_steady_state.py` (see D4-A) | external MON-RECORD JSONL |

### D4-A — 7-day steady-state record (go-live 2.4)

Full runbook: [mon-steady-state-7d.md](mon-steady-state-7d.md)

Once per calendar day on staging (HSS `D:\vita`):

```powershell
cd D:\vita
python scripts/observability/record_mon_steady_state.py
```

- Appends one line per UTC day to `logs/mon-steady-state-record.jsonl` (gitignored).
- Gate: **7 consecutive** calendar days with steady-state `missed=0`.
- Do not run on days with active fire-drill inject (wait 15m after drill).
- Archive JSONL to external ops storage as `MON-RECORD-YYYY-MM-NNN` when `gate_met=true`.

```powershell
python scripts/observability/record_mon_steady_state.py --json
```

### D4-B — Escalation webhook live drill (go-live 2.3)

Full runbook: [escalation-webhook-drill.md](escalation-webhook-drill.md)

**Do not** treat `--dry-run` as 2.3 acceptance.

Solo HSS (local capture proof):

```powershell
cd D:\vita
python scripts/observability/drill_escalation_webhook.py --dry-run
python scripts/observability/drill_escalation_webhook.py --local-capture
```

External channel (optional):

```powershell
$env:ESCALATION_WEBHOOK_URL = "https://hooks.example.com/..."
python scripts/observability/drill_escalation_webhook.py
```

Evidence: `logs/webhook-drill-proof.jsonl` with `ok=true`, archive as `WEBHOOK-DRILL-YYYY-MM-NNN`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `python: command not found` in deploy job | Missing setup-python | Fixed in deploy.yml (`actions/setup-python@v5` before python steps) |
| Remote postgres fails on fresh host | Image not built | `ssh_compose_deploy.sh` runs `docker compose build postgres` |
| Smoke timeout on host | Stack not ready | Check `docker compose ps`; increase `SMOKE_MAX_WAIT_SEC` |
| Rollback image missing | Tag not loaded on host | `docker tag vita-api:local vita-api:<sha>` before rollback |
| Rollback uses wrong image | `VITA_API_IMAGE` still set in shell | `Remove-Item Env:\VITA_API_IMAGE` then re-run rollback |
| `rollback.ps1` ignores `-PreviousImageTag` | WSL bash does not inherit PowerShell `$env:` | Fixed: `rollback.ps1` passes tag via `bash -c export ...` |
| Smoke fails immediately after rollback | vita-api not healthy yet | Fixed: `rollback.sh` uses `--wait`; increase `SMOKE_MAX_WAIT_SEC` |

---

## Related

- [deploy.md](deploy.md) — workflow reference and rollback appendix
- [github-setup-c-zone.md](github-setup-c-zone.md) — secrets and branch protection
- [monitoring.md](monitoring.md) — Grafana, alerts, steady-state
- [mon-steady-state-7d.md](mon-steady-state-7d.md) — 7-day MON record (2.4)
- [escalation-webhook-drill.md](escalation-webhook-drill.md) — webhook live / local-capture (2.3)
- [branch-strategy.md](../governance/branch-strategy.md) — `v1.0.0-rc.2` tagging policy
