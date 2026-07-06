# Monitoring and Alerting

Version: 1.0 (P5-1)

## P5-1 live stack (Grafana + VM scrape + clinical alerts)

Start observability services:

```powershell
python scripts/observability/render_grafana_alert_contact.py
docker compose --env-file config/.env.compose up -d victorialogs vmsingle grafana vita-api
python scripts/observability/verify_p5_monitoring.py
```

| URL | Service |
|-----|---------|
| http://127.0.0.1:3001 | Grafana (admin password from `config/.env.compose`) |
| http://127.0.0.1:8428 | VictoriaMetrics |
| http://127.0.0.1:9428/select/vmui | VictoriaLogs UI |
| http://127.0.0.1:8080/metrics | vita-api Prometheus metrics |

**Dashboards (provisioned):**

- **VITA Crisis Overview** — `grafana/provisioning/dashboards/json/vita_crisis_overview.json`
- **VITA SLO Overview** — `grafana/provisioning/dashboards/json/vita_slo_overview.json`

**Clinical alert routing:**

- Grafana rule: `grafana/provisioning/alerting/crisis_interception_rate.yaml`
- Contact point: `grafana/provisioning/alerting/contactpoints.yaml` (rendered via `render_grafana_alert_contact.py`)
- Notification policy: `grafana/provisioning/alerting/policies.yaml` (routes `severity=clinical`)
- Optional webhook: set `GRAFANA_CLINICAL_ALERT_WEBHOOK_URL` or `ESCALATION_WEBHOOK_URL` in `config/.env.compose`

**Steady-state verification:**

```powershell
python scripts/observability/verify_p5_monitoring.py
```

LogsQL baseline (zero missed interceptions): `config/observability/crisis_interception_missed.logsql`

## P5-2 operations runbooks

| Document | Purpose |
|----------|---------|
| [crisis-playbook.md](crisis-playbook.md) v1.0 | Clinical internal response, L4–5 escalation, missed interception |
| [incident.md](incident.md) v1.0 | S1–S4 severity, S2 language regression |
| [on-call.md](on-call.md) | Roster template, escalation chain |
| [troubleshooting.md](troubleshooting.md) | Symptom → command → expected output |
| [tabletop-s2-language-regression.md](tabletop-s2-language-regression.md) | S2 drill (< 30 min) |

Escalation webhook drill:

```powershell
python scripts/observability/drill_escalation_webhook.py --dry-run
python scripts/observability/drill_escalation_webhook.py
```

## Components

| Component | Endpoint / sink | Health probe |
|-----------|-----------------|--------------|
| vita-api | `GET /health`, `GET /health/engines`, `GET /metrics` | platform_engine |
| PostgreSQL | via platform probe | pg_extension:* |
| Redis | via platform probe | redis |
| VictoriaLogs | `GET /health` on :9428 | platform_engine victorialogs |
| VictoriaMetrics | `:8428` (scrapes vita-api `/metrics` via `config/observability/victoriametrics-scrape.yml`) | optional metrics scrape |
| Grafana | `:3001` | provisioning in `grafana/provisioning/` |
| Seele LLMs | `:8081-8085` /health | compute_engine |

## Chat latency histogram (P4-3)

Instrumented in `app/metrics/chat_latency_metrics.py`. Recorded from both runtime chat paths:

- Orchestrator (default `/chat` path): `Orchestrator._record_chat_processing_latency` on every turn exit (success and exception), path derived from `risk_level` via `resolve_processing_path_from_risk_level`.
- Safety hub path: `EmotionalSafetyHub._record_hub_processing_latency` on every hub exit.

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `vita_chat_processing_seconds` | Histogram | `path=normal\|crisis` | Chat turn wall time (orchestrator + hub) |

Grafana: **VITA SLO Overview** (`grafana/provisioning/dashboards/json/vita_slo_overview.json`).

PromQL p95 by path:

```
histogram_quantile(0.95, sum by (le, path) (rate(vita_chat_processing_seconds_bucket[5m])))
```

Scrape job: `config/observability/victoriametrics-scrape.yml` (target `vita-api:8080/metrics`).

### Multiprocess aggregation (required for multi-worker deployments)

`vita-api` runs 4 uvicorn workers (`WORKERS=4`). Each worker has an isolated
Prometheus registry, so `GET /metrics` must aggregate across workers or scraped
values are fragmented (one worker only). This is enabled via:

- `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc` (env, set in `docker-compose.yml`).
- A `tmpfs` mount at that path, cleared on every container (re)start.
- `GET /metrics` builds a `CollectorRegistry` + `MultiProcessCollector` when the env var is set (`app/main.py`).
- `multiprocess.mark_process_dead(pid)` on worker shutdown (`app/main.py` lifecycle).

Host single-process dev runs (`uvicorn --reload`) leave the env var unset and
use the default in-process registry. Per-process metrics (`python_gc_*`,
`process_*`) are not exported in multiprocess mode by design.

## Crisis interception metrics (P2-C)

Instrumented in `app/metrics/crisis_metrics.py`, called from `EmotionalSafetyHub.process_user_input`.

| Metric | Type | Meaning |
|--------|------|---------|
| `vita_crisis_signals_total{risk_band}` | Counter | Crisis signal detected (risk >= threshold, keywords, or indicators) |
| `vita_crisis_intercepted_total` | Counter | Final outcome companion-safe |
| `vita_crisis_missed_total` | Counter | Signal present but outcome not intercepted |
| `vita_crisis_interception_rate` | Gauge | intercepted / signals (1.0 when no signals yet) |

Scrape: `GET http://vita-api:8080/metrics` (VictoriaMetrics / Prometheus).

VictoriaLogs events (no user message content):

```
service:"vita-api" log_type:"crisis" event_type:"crisis_interception"
```

Fields: `outcome` (`intercepted` | `missed`), `risk_level`, `risk_band`, `escalated`.

## VictoriaLogs queries (LogsQL)

Error rate (app):

```
service:"vita-api" log_type:"app" level:"ERROR"
```

Crisis interception outcomes:

```
service:"vita-api" log_type:"crisis" event_type:"crisis_interception"
| stats by (outcome) count()
```

Verify private not shipped (should return empty if misconfigured):

```
service:"vita-api" log_type:"private"
```

UI: `http://127.0.0.1:9428/select/vmui`

## Alerts (P2-C codified)

### LogsQL: missed interception (any in window)

File: `config/observability/crisis_interception_missed.logsql`

```
service:"vita-api" log_type:"crisis" event_type:"crisis_interception" outcome:"missed" source:"safety_hub"
| stats count() as missed
| filter missed:>0
```

Rolling window for steady-state verification (P5-1):

```
_time:15m service:"vita-api" log_type:"crisis" event_type:"crisis_interception" outcome:"missed" source:"safety_hub" source:"safety_hub"
| stats count() as missed
| filter missed:>0
```

Action: clinical supervisor review per `docs/operations/crisis-playbook.md`.

### Grafana: interception rate below 95%

File: `grafana/provisioning/alerting/crisis_interception_rate.yaml`

- Datasource: VictoriaMetrics (`vita-vmsingle`)
- Condition: `vita_crisis_interception_rate < 0.95` AND `sum(increase(vita_crisis_signals_total[15m])) > 5`
- For: 5 minutes

Requires Grafana provisioning mount (`docker-compose.yml` grafana volumes) and scrape of vita-api `/metrics`.

## Other recommended alerts

| Alert | Condition | Action |
|-------|-----------|--------|
| API down | `/health` non-200 3x | incident S1 |
| Error spike | ERROR count > baseline x3 in 5m | investigate logs |
| Platform degraded | postgres down in engines | incident S2 |

## Log shipper

`ENABLE_VICTORIA_LOGS_SHIPPER=true` in config; private log_type excluded in `app/logger.py`.

Structured crisis metric fields are merged via `record.vita_fields` on the VictoriaLogs shipper.

## Tests

```powershell
python -m pytest tests/metrics/test_crisis_metrics.py tests/metrics/test_chat_latency_metrics.py -q
```
