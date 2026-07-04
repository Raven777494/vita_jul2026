# Service Level Objectives (SLO)

Version: 0.2 (P4-3)

## Scope

VITA Logic Engine (`vita-api`) and crisis safety path (`EmotionalSafetyHub`).

## Objectives

| ID | SLO | Target (30d) | Measurement | Alert |
|----|-----|--------------|-------------|-------|
| SLO-1 | API availability | 99.5% | Synthetic `GET /health` every 60s | 3 consecutive failures |
| SLO-2 | Chat latency p95 (normal) | < 3s | `histogram_quantile(0.95, sum by (le, path) (rate(vita_chat_processing_seconds_bucket{path="normal"}[5m])))` | p95 > 3s for 15m |
| SLO-3 | Crisis path latency p95 | < 5s | Same query with `path="crisis"` | p95 > 5s for 15m |
| SLO-4 | Crisis interception rate | >= 95% | `vita_crisis_interception_rate` when `sum(increase(vita_crisis_signals_total[15m])) > 5` | Grafana rule (see monitoring.md) |
| SLO-5 | Dependency CVE gate | 0 critical open | pip-audit CI | CI failure |

## Instrumentation (P4-3)

| Component | Location |
|-----------|----------|
| Histogram | `app/metrics/chat_latency_metrics.py` — `vita_chat_processing_seconds{path="normal\|crisis"}` |
| Hub wiring | `EmotionalSafetyHub._record_hub_processing_latency()` on every turn exit |
| Path label | `crisis` when `is_crisis_signal()` true (same definition as interception metrics) |
| Scrape | `config/observability/victoriametrics-scrape.yml` → vmsingle `-promscrape.config` |
| Dashboard | `grafana/provisioning/dashboards/json/vita_slo_overview.json` |

Verify locally (stack running):

```powershell
curl -s http://127.0.0.1:8080/metrics | findstr vita_chat_processing_seconds
curl -s "http://127.0.0.1:8428/api/v1/query?query=vita_chat_processing_seconds_count"
```

## Error budget

- **Availability:** 0.5% monthly downtime (~3.6 hours / 30d).
- When budget exhausted: freeze features; focus on reliability and clinical path.

## Crisis path priority

Under load, crisis turns must not be starved by normal chat:

1. Hub processing records `path=crisis` when crisis signal detected.
2. SLO-3 reviewed separately from SLO-2 in Grafana panel **Chat processing latency p95 (normal vs crisis)**.
3. Future: separate worker queue for risk >= 4 (backlog).

## Review

Monthly: compare Grafana/VictoriaMetrics to targets; record in tech debt review log (see [../governance/RACI.md](../governance/RACI.md)).

## Related

- [monitoring.md](monitoring.md)
- [crisis-playbook.md](crisis-playbook.md)
- `docs/governance/execution-program.md` P4-3
