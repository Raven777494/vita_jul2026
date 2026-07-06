# On-Call Runbook (Template)

Version: 1.0 (P5-2)  
Status: Template — assign names before production go-live

**Roster and personal contact details live outside this repository** (encrypted ops store, per [../security/secrets-policy.md](../security/secrets-policy.md)).

## Purpose

Define who responds to VITA production incidents, how escalation works, and when clinical advisors must be consulted.

## Roles

| Role | Responsibility | Typical hours |
|------|----------------|---------------|
| On-call primary (Ops) | S1/S3 outages, deploy rollback, infra | Rotation |
| On-call secondary (Eng) | Code fix, metrics/logs investigation | Backup |
| Clinical advisor | S2 language regression, missed interception review | Business hours + page for S2 |
| Product owner | User impact comms (internal) | Business hours |

## Named roster (fill before go-live)

| Role | Name | Primary contact | Backup contact |
|------|------|-----------------|----------------|
| On-call primary | TBD | TBD | TBD |
| On-call secondary | TBD | TBD | TBD |
| Clinical advisor | TBD | TBD | TBD |
| Product owner | TBD | TBD | TBD |

## Escalation chain

1. **Alert fires** (Grafana clinical rule, VictoriaLogs missed query, `/health` down)
2. **On-call primary** acknowledges within 15 minutes (S1/S2) or 4 hours (S3)
3. **Eng secondary** engaged if not resolved in 30 minutes (S1/S2)
4. **Clinical advisor** engaged for:
   - `severity=clinical` Grafana alerts
   - Any `outcome:missed` in VictoriaLogs (see [crisis-playbook.md](crisis-playbook.md))
   - S2 language policy regression ([incident.md](incident.md))
5. **Product owner** informed for user-visible outage > 15 minutes

## Alert routing (configured)

| Source | Route | Runbook |
|--------|-------|---------|
| Grafana `vita-clinical` (interception rate) | `GRAFANA_CLINICAL_ALERT_WEBHOOK_URL` or Grafana UI | [crisis-playbook.md](crisis-playbook.md) |
| VictoriaLogs missed (LogsQL) | Manual / Grafana VL alert | [crisis-playbook.md](crisis-playbook.md) |
| Escalation L4–5 | `ESCALATION_WEBHOOK_URL` via `escalation_notifier` | [crisis-playbook.md](crisis-playbook.md) |
| API `/health` non-200 | Synthetic / ops monitor | [incident.md](incident.md) |

Render Grafana contact point before compose up:

```powershell
python scripts/observability/render_grafana_alert_contact.py
```

## Shift handoff checklist

- [ ] Review open Grafana alerts (VITA Clinical folder)
- [ ] Run `python scripts/observability/verify_p5_monitoring.py --skip-steady-state`
- [ ] Confirm `docker compose ps` — postgres, redis, vita-api, vmsingle, grafana healthy
- [ ] Note any open TD items affecting ops ([../governance/tech-debt-register.md](../governance/tech-debt-register.md))

## Related

- [incident.md](incident.md) — severity levels and S1/S2 playbooks
- [crisis-playbook.md](crisis-playbook.md) — clinical internal response
- [troubleshooting.md](troubleshooting.md) — symptom to command index
- [../governance/RACI.md](../governance/RACI.md) — accountability matrix
- [../governance/clinical-signoff-template.md](../governance/clinical-signoff-template.md) — clinical PR sign-off
