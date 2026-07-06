# Tabletop Exercise: S2 Language Regression

Version: 1.0 (P5-2)  
Type: Internal drill (no production user impact)  
Target duration: **Under 30 minutes**

## Objective

Validate that on-call and clinical roles can detect, contain, and remediate a companion language policy regression using repo runbooks only.

## Participants

| Role | Responsibility in drill |
|------|-------------------------|
| Facilitator | Injects scenario, times steps |
| On-call Eng | Runs commands, containment |
| Clinical advisor | Reviews policy impact, sign-off criteria |
| Scribe | Records times and gaps (external doc) |

Minimum: Facilitator + On-call Eng. Clinical advisor required for full P5-2 sign-off.

## Scenario inject

> CI has passed, but VictoriaLogs steady-state check reports `missed=1` in the last 15 minutes. Grafana shows interception rate at 0.88 with 8 signals in 15m. A developer suspects a recent orchestrator change bypassed `validate_user_facing_text`.

## Exercise steps

| # | Step | Owner | Max time | Success criteria |
|---|------|-------|----------|------------------|
| 1 | Acknowledge alert | On-call | 2 min | Severity classified S2 |
| 2 | Run troubleshooting sweep | On-call | 5 min | [troubleshooting.md](troubleshooting.md) quick health done |
| 3 | Query VictoriaLogs missed events | On-call | 5 min | LogsQL returns count and risk_band |
| 4 | Run clinical test suite | On-call | 5 min | `pytest tests/clinical/` — note failures |
| 5 | Open crisis playbook missed section | Clinical | 3 min | Steps 1–6 understood |
| 6 | Simulate contain decision | On-call | 3 min | Document rollback vs hotfix choice |
| 7 | Run escalation drill (dry-run) | On-call | 2 min | `drill_escalation_webhook.py --dry-run` OK |
| 8 | Debrief | All | 5 min | Gaps logged |

## Commands checklist (participant copy)

```powershell
python scripts/observability/verify_p5_monitoring.py
python -m pytest tests/clinical/test_companion_language_policy.py tests/clinical/test_crisis_scenarios.py -q
python scripts/observability/drill_escalation_webhook.py --dry-run
python app/tests/system_alignment_checker.py
```

VictoriaLogs (browser): `http://127.0.0.1:9428/select/vmui`

```
_time:15m service:"vita-api" log_type:"crisis" event_type:"crisis_interception" outcome:"missed" source:"safety_hub"
| stats by (risk_band) count() as missed
```

## Record template (store outside repo)

| Item | Value |
|------|-------|
| Date | |
| Participants | |
| Duration (minutes) | |
| Completed under 30 min? | Yes / No |
| Steps skipped | |
| Runbook gaps | |
| Actions before next drill | |
| Clinical advisor sign-off | |

## Pass criteria (P5-2 acceptance)

- [ ] All eight steps attempted
- [ ] Wall-clock time < 30 minutes
- [ ] On-call completed LogsQL + pytest + drill commands without ad-hoc improvisation
- [ ] Scribe record filed in external ops store
- [ ] Any runbook gap filed as TD or doc PR within 5 business days

## Related

- [incident.md](incident.md) — S2 definition
- [crisis-playbook.md](crisis-playbook.md) — missed interception procedure
- [on-call.md](on-call.md) — escalation chain
