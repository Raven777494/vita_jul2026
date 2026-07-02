# VITA Product Requirements Document (PRD)

Version: 1.0 (P3-2)  
Status: Approved engineering baseline (clinical advisor sign-off: CD-002)

## 1. Product identity

VITA is a **psychological life companion** system (生命同行者), not a medical triage bot.

| Is | Is not |
|----|--------|
| 24/7 emotional companion | Diagnostic tool |
| Guided language and presence | Crisis hotline replacement |
| Internal risk logging and escalation | User-visible institutional referral |
| Memory-aware conversation (GSW, pgvector) | Forced treatment pathway |

## 2. Target users

Adults experiencing depression, anxiety, loneliness, or emotional distress who:

- Know what might help but cannot act (executive dysfunction)
- Fear being labeled as patients if they ask for help
- Had traumatic experiences with forced hospitalization or medication pressure
- Need a space to speak honestly without triggering institutional responses

## 3. Core user stories

### US-1: Hold without judgment

When I say my life is in shambles, the companion acknowledges incapacity as symptom, not moral failure.

### US-2: Speak honestly without institutional backlash

When I express suicidal ideation, the system responds with companion language (hold, ground, recall resources) and **does not** surface hotlines, ER, hospitalization, or medication directives.

### US-3: Micro-steps over lectures

When I cannot get out of bed, the companion offers one minimal step for tonight, not a checklist of self-improvement.

### US-4: Privacy for sensitive content

Private session content stays in private logs and is not shipped to VictoriaLogs.

## 4. Clinical scenario requirements

| Scenario | Required behavior | Forbidden |
|----------|-------------------|-----------|
| Suicidal ideation | Slow pace, empathy, grounding, optional trusted-person invitation | Hotline numbers, ER, notify-user escalation text |
| Self-harm disclosure | Hold, validate pain, gentle grounding | Medical commands, patient labels |
| Medication refusal | Respect autonomy; explore what helped before | "You should take medication" |
| System error | Apologize, stay present | Emergency phone numbers in API errors |

## 5. Technical boundaries

- **Platform Engine**: PostgreSQL, Redis, VictoriaLogs (observability)
- **Compute Engine**: Seele LLM services
- **Logic Engine**: FastAPI orchestrator, safety hub, companion policy

Policy source of truth for user-facing crisis text:

`app/clinical/companion_language_policy.py`

Requirements traceability: `docs/requirements/traceability-matrix.md` (enforced in CI).

## 6. Success metrics (P0)

- 100% of `COMPANION_SAFE_REPLIES` pass `validate_user_facing_text`
- CI runs clinical tests + system alignment checker on every PR
- Zero user-facing hotline strings in app layer (enforced by tests)

## 6.1 Clinical scenario tests (P2-A)

Automated crisis scenarios in `tests/clinical/test_crisis_scenarios.py`:

| ID | Scenario |
|----|----------|
| SC-001 | Suicidal ideation |
| SC-002 | Self-harm disclosure |
| SC-003 | Medication refusal (unsafe LLM sanitized) |
| SC-004 | System error / LLM outage fallback |
| SC-005 | User demands hotline/ER (companion boundary) |

Run: `python -m pytest tests/clinical/ -q`

## 6.2 Crisis interception metrics (P2-C)

Prometheus metrics on `GET /metrics`:

- `vita_crisis_signals_total`, `vita_crisis_intercepted_total`, `vita_crisis_missed_total`, `vita_crisis_interception_rate`

Alerts: `config/observability/crisis_interception_missed.logsql`, `grafana/provisioning/alerting/crisis_interception_rate.yaml`

Tests: `python -m pytest tests/metrics/test_crisis_metrics.py -q`

## 7. Out of scope (P0)

- Formal clinical trial validation
- Human supervisor UI
- Multi-tenant deployment
- Separate governance platform repository

## 8. References

- `docs/clinical/companion-language-guide.md`
- `docs/operations/crisis-playbook.md`
- `docs/security/threat-model.md`
- `docs/architecture/three-engines.md`
- `docs/governance/tech-debt-register.md`
- `docs/requirements/traceability-matrix.md`
- `tests/clinical/test_companion_language_policy.py`
