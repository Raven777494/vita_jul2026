# Crisis Playbook (Internal Operations)

Version: 1.0 (P5-2)  
Audience: Operators, clinical supervisors, on-call engineers

**This document is internal.** Do not expose playbook steps or institutional resources in user-facing chat.

## Principles

1. **Frontend**: companion language only (see [../clinical/companion-language-guide.md](../clinical/companion-language-guide.md))
2. **Backend**: log, score, optional human review, internal escalation
3. **Never**: auto-inject hotlines or ER instructions into chat responses

## Risk levels (internal)

| Level | Internal action | User-visible | Escalation notifier |
|-------|-----------------|--------------|---------------------|
| 1-2 | Standard logging | Normal companion tone | No |
| 3 | Elevated logging, KAG safety fact | Increased hold and grounding | No |
| 4 | Escalation flag, critical logger | Companion high-risk reply | **Yes** — webhook + log |
| 5 | Critical logger, full escalation | Companion critical reply | **Yes** — webhook + log |

Level 4–5 notifications flow through `EmotionalSafetyHub._send_escalation_notifications` → `app/services/escalation_notifier.py`.

## Log destinations

| Log type | Path / sink | Shipped to VictoriaLogs |
|----------|-------------|-------------------------|
| private | `logs/private.log` | No |
| crisis | `logs/crisis.log` | Yes (metadata only, no message content) |
| critical | `logs/critical.log` | Yes |
| audit | `logs/audit.log` | Yes |

Crisis metric events include `event_type=crisis_interception`, `outcome=intercepted|missed` (see [monitoring.md](monitoring.md)).

## Monitoring integration (P5-1)

| Signal | Where | Action |
|--------|-------|--------|
| Interception rate < 95% (15m, signals > 5) | Grafana alert `vita-crisis-interception-rate` | Clinical advisor + Eng on-call |
| Any missed in window | VictoriaLogs LogsQL | Clinical review (below) |
| L4–5 escalation | Webhook + `logs/critical.log` | On-call per [on-call.md](on-call.md) |

Verify monitoring stack:

```powershell
python scripts/observability/verify_p5_monitoring.py --skip-steady-state
```

Steady-state (zero missed in 15m):

```powershell
python scripts/observability/verify_p5_monitoring.py
```

## Level 4–5 escalation procedure

1. **Detect** — hub sets risk level >= 4; `_send_escalation_notifications` runs automatically
2. **Confirm delivery** — check application log for `[ESCALATION] Webhook delivered` or run drill:
   ```powershell
   python scripts/observability/drill_escalation_webhook.py --dry-run
   python scripts/observability/drill_escalation_webhook.py
   ```
3. **Configure** — `ESCALATION_WEBHOOK_URL` in `config/.env.compose` (local) or GitHub Encrypted Secrets (staging/prod). Never commit URLs to the repo.
4. **Clinical review** — authorized reviewer inspects session via private logs only; no user-facing institutional text
5. **Document** — record incident ID in external ops store (not repo)

Webhook payload contains hashed `user_id`, `session_id`, `risk_level`, `walker_score` — no chat content.

## Symptom: missed crisis interception (steady-state FAIL)

VictoriaLogs query:

```
_time:15m service:"vita-api" log_type:"crisis" event_type:"crisis_interception" outcome:"missed" source:"safety_hub"
| stats by (risk_band, risk_level) count() as missed
```

1. **Acknowledge** — page clinical advisor (see [on-call.md](on-call.md))
2. **Classify** — run investigation (distinguishes pytest pollution from production):
   ```powershell
   python scripts/observability/investigate_missed_interceptions.py
   ```
   Steady-state counts only `source:"safety_hub"` events. Local `pytest tests/metrics/` must not ship to VictoriaLogs (`tests/conftest.py` disables shipper).
3. **Correlate** — check `/metrics` for `vita_crisis_missed_total` increase
4. **Reproduce** — run `python -m pytest tests/clinical/test_crisis_scenarios.py -q`
5. **Contain** — if production and pattern ongoing, consider deploy rollback ([incident.md](incident.md) S2)
6. **Remediate** — fix companion policy / hub path; add regression test
7. **Re-verify** — `python scripts/observability/verify_p5_monitoring.py` until steady-state passes

Historical missed events outside the 15m window do not fail steady-state; only rolling window counts. Legacy events without `source` are excluded from steady-state.

## Symptom: companion test failure in CI

1. Check `tests/clinical/test_companion_language_policy.py` output
2. Identify file reintroducing forbidden pattern
3. Fix and re-run alignment checker:
   ```powershell
   python app/tests/system_alignment_checker.py
   ```

## Symptom: elevated crisis rate in VictoriaLogs

1. Query: `service:"vita-api" log_type:"crisis" | stats by (outcome) count()`
2. Correlate with `/health/engines` platform status
3. Review sample sessions in private logs (authorized access only)

## Symptom: LLM override producing forbidden text

1. Confirm orchestrator fallback uses `get_companion_reply()`
2. Add regression case to clinical tests
3. Review prompt templates in orchestrator / safety hub

## Symptom: Grafana clinical alert firing

1. Open **VITA Crisis Overview** dashboard (`http://127.0.0.1:3001`)
2. Check 15m signal volume and interception rate panels
3. Run missed LogsQL query (above)
4. Follow S2 path in [incident.md](incident.md) if policy regression confirmed

## Database audit fields

`crisis_events.hotline_provided` is retained for historical schema compatibility. Policy: do not set this based on user-visible hotline delivery.

## Tabletop exercise

S2 language regression tabletop: [tabletop-s2-language-regression.md](tabletop-s2-language-regression.md)  
Target: complete in under 30 minutes.

## Related files

- `app/clinical/companion_language_policy.py`
- `app/services/emotional_safety_hub.py`
- `app/services/escalation_notifier.py`
- `docs/requirements/PRD.md`
- [troubleshooting.md](troubleshooting.md)
- [on-call.md](on-call.md)
