# Crisis Playbook (Internal Operations)

Version: 0.1 (P0)  
Audience: Operators, clinical supervisors, on-call engineers

**This document is internal.** Do not expose playbook steps or institutional resources in user-facing chat.

## Principles

1. **Frontend**: companion language only (see `docs/clinical/companion-language-guide.md`)
2. **Backend**: log, score, optional human review
3. **Never**: auto-inject hotlines or ER instructions into chat responses

## Risk levels (internal)

| Level | Internal action | User-visible |
|-------|-----------------|--------------|
| 1-2 | Standard logging | Normal companion tone |
| 3 | Elevated logging, KAG safety fact | Increased hold and grounding |
| 4 | Escalation flag, critical logger | Companion high-risk reply |
| 5 | Critical logger, escalation notifier (webhook optional) | Companion critical reply |

## Log destinations

| Log type | Path / sink | Shipped to VictoriaLogs |
|----------|-------------|-------------------------|
| private | `logs/private.log` | No |
| crisis | `logs/crisis.log` | Yes (non-private) |
| critical | `logs/critical.log` | Yes |
| audit | `logs/audit.log` | Yes |

## Incident response (technical)

### Symptom: companion test failure in CI

1. Check `tests/clinical/test_companion_language_policy.py` output
2. Identify file reintroducing forbidden pattern
3. Fix and re-run alignment checker

### Symptom: elevated crisis rate in VictoriaLogs

1. Query: `service:"vita-api" log_type:"crisis"`
2. Correlate with `/health/engines` platform status
3. Review sample sessions in private logs (authorized access only)

### Symptom: LLM override producing forbidden text

1. Confirm orchestrator fallback uses `get_companion_reply()`
2. Add regression case to clinical tests
3. Review prompt templates in orchestrator / safety hub

## Human review hook (placeholder)

`emotional_safety_hub._send_escalation_notifications` delegates to `app/services/escalation_notifier.py`. Configure `ESCALATION_WEBHOOK_URL` via GitHub Encrypted Secrets or host env — never hard-code credentials or webhook URLs in the repository.

## Database audit fields

`crisis_events.hotline_provided` is retained for historical schema compatibility. P0 policy: do not set this based on user-visible hotline delivery.

## Related files

- `app/clinical/companion_language_policy.py`
- `app/services/emotional_safety_hub.py`
- `docs/requirements/PRD.md`
