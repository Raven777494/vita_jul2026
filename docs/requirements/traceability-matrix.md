# Requirements Traceability Matrix

Version: 1.0 (P6-2)  
PRD: `docs/requirements/PRD.md` v1.0 Approved (P6-2)  
CI gate: `python scripts/governance/check_traceability.py`

Link every active requirement to implementation and automated verification.

## Active requirements

| ID | Type | Requirement (summary) | Code | Test |
|----|------|----------------------|------|------|
| US-1 | User story | Hold without judgment | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| US-2 | User story | No institutional backlash on suicidal ideation | `app/clinical/companion_language_policy.py` | `tests/clinical/test_crisis_scenarios.py` |
| US-3 | User story | Micro-steps over lectures (companion prompts) | `app/services/emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| US-4 | User story | Private content not shipped to VictoriaLogs | `app/logger.py` | `tests/clinical/test_private_log_isolation.py` |
| P0-1 | Success metric | COMPANION_SAFE_REPLIES pass forbidden scan | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| P0-2 | Success metric | CI clinical + alignment on every PR | `.github/workflows/ci.yml` | `CI:test-and-alignment` |
| P0-3 | Success metric | No user-facing hotline strings in app layer | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| SC-001 | Clinical | Suicidal ideation | `app/services/emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-002 | Clinical | Self-harm disclosure | `app/services/emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-003 | Clinical | Medication refusal sanitize | `app/services/emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-004 | Clinical | System error fallback | `app/utils/error_handler.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-005 | Clinical | User demands hotline/ER boundary | `app/clinical/companion_language_policy.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-006 | Red team | Prompt injection hotline | `app/clinical/user_facing_gate.py` | `tests/clinical/test_red_team_prompts.py` |
| SC-007 | Red team | Jailbreak institutional override | `app/services/emotional_safety_hub.py` | `tests/clinical/test_red_team_prompts.py` |
| SC-008 | Red team | DAN jailbreak hotline leak | `app/services/emotional_safety_hub.py` | `tests/clinical/test_red_team_prompts.py` |
| SC-009 | Red team | Benign input poisoned LLM output | `app/services/emotional_safety_hub.py` | `tests/clinical/test_red_team_prompts.py` |
| SC-010 | Red team | Orchestrator finalize injection block | `app/orchestrator.py` | `tests/clinical/test_red_team_prompts.py` |
| MET-1 | Metric | Crisis interception rate | `app/metrics/crisis_metrics.py` | `tests/metrics/test_crisis_metrics.py` |
| SEC-1 | Security | Secrets not in compose YAML | `docker-compose.yml` | `tests/platform/test_compose_env.py` |
| SEC-2 | Security | pip-audit CVE gate | `scripts/security/pip_audit_check.py` | `CI:dependency-audit` |
| GATE-1 | Safety path | Orchestrator user-facing companion gate | `app/clinical/user_facing_gate.py` | `tests/clinical/test_orchestrator_companion_gate.py` |

## Planned (P4+ — not gated by traceability checker)

| ID | Type | Requirement | Code (target) | Test (target) |
|----|------|-------------|---------------|---------------|
| SLO-3 | Performance | Crisis p95 under 5s | `app/services/emotional_safety_hub.py` | `docs/operations/slo.md` |

## Maintenance

1. Add a row under **Active requirements** before merging any new `SC-*` in `tests/clinical/crisis_scenarios.py` or `tests/clinical/red_team_scenarios.py`.
2. Run `python scripts/governance/check_traceability.py` locally.
3. Update `docs/requirements/PRD.md` section 6.1 when SC IDs change.

## PRD section 4 mapping

| PRD scenario | Matrix ID |
|--------------|-----------|
| Suicidal ideation | SC-001 |
| Self-harm disclosure | SC-002 |
| Medication refusal | SC-003 |
| System error | SC-004 |
| Forbidden institutional pathway (user demand) | SC-005 |
| Prompt injection hotline | SC-006 |
| Institutional jailbreak | SC-007 |
| DAN jailbreak | SC-008 |
| Poisoned LLM output | SC-009 |
| Orchestrator injection block | SC-010 |
