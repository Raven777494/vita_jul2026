# Prompt Injection Mitigations

Version: 0.1 (P4-2 / TD-004)

## Defense layers

| Layer | Component | Purpose |
|-------|-----------|---------|
| Input | `app/security/prompt_sanitizer.py` | Detect and neutralize injection phrases before LLM prompt assembly |
| Output | `app/clinical/user_facing_gate.py` | Block hotline/ER/institutional text in user-visible replies |
| Output | `app/clinical/companion_language_policy.py` | Forbidden pattern validation |
| CI | `tests/clinical/test_red_team_prompts.py` | SC-006..010 adversarial scenarios |
| CI | `tests/security/test_prompt_injection.py` | Sanitizer unit tests |

## Sanitizer behavior

Applied at:

- `Orchestrator` user message entry (with audit logging)
- `EmotionalSafetyHub.process_user_input` (with audit logging)
- `LLMService.infer_async` (defense in depth, audit disabled to avoid duplicate logs)

Detection patterns include: ignore-previous-instructions, system override, jailbreak role-play, hotline injection, institutional override, model delimiter injection.

Matched phrases are replaced with `[filtered]`. Model turn delimiters in user text are stripped.

## Audit logging (no user content in VictoriaLogs)

Injection detections call `AuditLogger.log_prompt_injection_attempt()`:

- Writes to `logs/audit.log` only (JSON metadata)
- Fields: `patterns_detected`, `input_length`, `user_id_hash`, `session_id`, `was_modified`
- Does **not** include raw user text (prevents adversarial payload exfiltration via log shipping)

VictoriaLogs receives audit JSON without user content. Private/crisis raw content remains in `private.log` / `crisis.log` per [session-isolation.md](session-isolation.md).

## Operator response

1. Query audit events: `event_type="prompt_injection_attempt"` in `logs/audit.log`
2. Correlate by `session_id` and `user_id_hash`
3. If sustained attack: rate-limit user/session; review session in private logs (authorized access)
4. Add regression case to `tests/security/test_prompt_injection.py` for new pattern

## Related

- [key-rotation-runbook.md](key-rotation-runbook.md)
- [threat-model.md](threat-model.md)
- TD-004 closed at P4-2 (ongoing model prompt hardening remains best practice)
