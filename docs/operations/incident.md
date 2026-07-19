# Incident Response

Version: 1.0 (P5-2)

## Severity levels

| Level | Example | Response time target | Primary owner |
|-------|---------|----------------------|---------------|
| S1 | Active data breach, widespread outage | Immediate | On-call Ops |
| S2 | Crisis language policy bypass, missed interception spike | Same day | Eng + Clinical advisor |
| S3 | Single service degraded (Redis, one LLM, Grafana) | Next business day | On-call Eng |
| S4 | CI failure, non-prod | Backlog | Engineering |

On-call roster: [on-call.md](on-call.md) (names stored outside repo).

## S1 / S2 playbook

1. **Identify** — VictoriaLogs, Grafana alerts, `/health`, `/health/engines`, user report
2. **Contain** — disable affected endpoint or feature flag if available; rollback deploy if needed
3. **Preserve** — private/crisis logs; do not delete evidence
4. **Communicate** — internal stakeholders per [on-call.md](on-call.md); no public detail on T3 content
5. **Remediate** — patch, redeploy, rotate secrets if needed ([../security/secrets-policy.md](../security/secrets-policy.md))
6. **Review** — post-incident note (external store); update threat model or tests

## S2: Crisis language regression

Trigger examples:

- Clinical pytest failure in production deploy path
- Grafana `vita-crisis-interception-rate` alert
- Steady-state verify: `missed > 0` in VictoriaLogs 15m window
- Forbidden pattern in user-facing output

Steps:

1. Acknowledge — notify clinical advisor ([on-call.md](on-call.md))
2. Run diagnostics:
   ```powershell
   python -m pytest tests/clinical/ -q
   python scripts/observability/verify_p5_monitoring.py
   rg "2389|熱線|For emergency" app/ tests/
   ```
3. Contain — roll back deploy if production affected
4. Remediate — fix policy/hub path; add regression test (SC-*)
5. Verify — alignment checker + P5 monitoring + clinical suite green
6. Tabletop follow-up if process gap found ([tabletop-s2-language-regression.md](tabletop-s2-language-regression.md))

Detailed clinical steps: [crisis-playbook.md](crisis-playbook.md)

## S3: Observability degradation

| Symptom | First action |
|---------|--------------|
| Grafana down | `docker compose --env-file config/.env.compose up -d grafana` |
| VM scrape down | Check `vita-api` health; restart `vmsingle` |
| Metrics empty | Confirm `PROMETHEUS_MULTIPROC_DIR` / worker count ([monitoring.md](monitoring.md)) |

Index: [troubleshooting.md](troubleshooting.md)

## Escalation webhook drill (P5-2 acceptance)

Before production go-live and after webhook URL rotation:

```powershell
python scripts/observability/drill_escalation_webhook.py --dry-run
python scripts/observability/drill_escalation_webhook.py
```

Expected: log backend OK; webhook OK when `ESCALATION_WEBHOOK_URL` configured.
Solo HSS: `python scripts/observability/drill_escalation_webhook.py --local-capture`
Full runbook: [escalation-webhook-drill.md](escalation-webhook-drill.md).

## Post-incident record (external)

Store outside repo:

| Field | Example |
|-------|---------|
| Incident ID | INC-2026-001 |
| Severity | S2 |
| Detected | ISO timestamp |
| Resolved | ISO timestamp |
| Root cause | One paragraph |
| Actions | Bullets |
| Clinical sign-off | Name + date (S2 only) |

## Related

- [crisis-playbook.md](crisis-playbook.md)
- [monitoring.md](monitoring.md)
- [on-call.md](on-call.md)
- [troubleshooting.md](troubleshooting.md)
- [tabletop-s2-language-regression.md](tabletop-s2-language-regression.md)
