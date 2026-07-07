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

### Acceptance

| Field | Value |
|-------|-------|
| Checklist item | 1.3 |
| Jobs required green | `Build and smoke`, `Deploy to host` |
| Image tag | `vita-api:<github.sha>` |
| Smoke | pass on host |

---

## D3 — Rollback drill (go-live 1.4)

**Owner (A):** OPS  
**Executor (R):** ENG  
**Goal:** Restore previous `vita-api` image after a failed or superseded deploy.

On the **deploy host** (after D2 succeeded at least once):

```bash
cd "${DEPLOY_PATH:-/opt/vita}"
export PREVIOUS_IMAGE_TAG=<known-good-git-sha>
bash scripts/deploy/rollback.sh
```

`rollback.sh`:

1. Restores `config/.env.compose.backup` if present
2. Retags `vita-api:${PREVIOUS_IMAGE_TAG}` as `vita-api:latest`
3. Recreates `vita-api` via compose
4. Runs `smoke_check.sh`

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
| **2.3** Escalation webhook live | `python scripts/observability/drill_escalation_webhook.py` (non dry-run) | delivery proof to configured channel |
| **2.4** Steady-state 7 days | `verify_p5_monitoring.py` steady-state over 7 days | external MON-RECORD |

Dry-run webhook (safe pre-check):

```powershell
python scripts/observability/drill_escalation_webhook.py --dry-run
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `python: command not found` in deploy job | Missing setup-python | Fixed in deploy.yml (`actions/setup-python@v5` before python steps) |
| Remote postgres fails on fresh host | Image not built | `ssh_compose_deploy.sh` runs `docker compose build postgres` |
| Smoke timeout on host | Stack not ready | Check `docker compose ps`; increase `SMOKE_MAX_WAIT_SEC` |
| Rollback image missing | Tag not loaded on host | Re-run D2 with known-good SHA or `docker load` |

---

## Related

- [deploy.md](deploy.md) — workflow reference and rollback appendix
- [github-setup-c-zone.md](github-setup-c-zone.md) — secrets and branch protection
- [monitoring.md](monitoring.md) — Grafana, alerts, steady-state
- [branch-strategy.md](../governance/branch-strategy.md) — `v1.0.0-rc.2` tagging policy
