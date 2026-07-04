# Monitoring and Alerting

Version: 0.3 (P4-3)

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

Instrumented in `app/metrics/chat_latency_metrics.py`, called from `EmotionalSafetyHub._record_hub_processing_latency`.

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `vita_chat_processing_seconds` | Histogram | `path=normal\|crisis` | Hub `process_user_input` wall time |

Grafana: **VITA SLO Overview** (`grafana/provisioning/dashboards/json/vita_slo_overview.json`).

PromQL p95 by path:

```
histogram_quantile(0.95, sum by (le, path) (rate(vita_chat_processing_seconds_bucket[5m])))
```

Scrape job: `config/observability/victoriametrics-scrape.yml` (target `vita-api:8080/metrics`).

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
service:"vita-api" log_type:"crisis" event_type:"crisis_interception" outcome:"missed"
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
