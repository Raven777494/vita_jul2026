# Service Level Objectives (SLO)

Version: 0.1 (P4 target — measure on staging before production)

## Scope

VITA Logic Engine (`vita-api`) and crisis safety path (`EmotionalSafetyHub`).

## Objectives

| ID | SLO | Target (30d) | Measurement | Alert |
|----|-----|--------------|-------------|-------|
| SLO-1 | API availability | 99.5% | Synthetic `GET /health` every 60s | 3 consecutive failures |
| SLO-2 | Chat latency p95 (normal) | < 3s | `vita_chat_processing_seconds{path="normal"}` | p95 > 3s for 15m |
| SLO-3 | Crisis path latency p95 | < 5s | `vita_chat_processing_seconds{path="crisis"}` | p95 > 5s for 15m |
| SLO-4 | Crisis interception rate | >= 95% | `vita_crisis_interception_rate` when signals > 5 / 15m | Grafana rule (see monitoring.md) |
| SLO-5 | Dependency CVE gate | 0 critical open | pip-audit CI | CI failure |

## Error budget

- **Availability:** 0.5% monthly downtime (~3.6 hours / 30d).
- When budget exhausted: freeze features; focus on reliability and clinical path.

## Crisis path priority

Under load, crisis turns (risk >= `CRISIS_SIGNAL_THRESHOLD`) must not be starved by normal chat:

1. Hub processing runs with explicit `path=crisis` metric label.
2. Future: separate worker queue for risk >= 4 (P4 engineering task).

## Review

Monthly: compare Grafana/VictoriaMetrics to targets; record in tech debt review log.

Implementation tasks: `docs/governance/execution-program.md` P4-3.
