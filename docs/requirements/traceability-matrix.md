# Requirements Traceability Matrix

Version: 0.1 (P3 — expand until 100% coverage)

Link PRD requirements to code and automated tests. CI checker: `scripts/governance/check_traceability.py` (P3-2).

| ID | Type | Requirement (summary) | Policy / code | Test |
|----|------|----------------------|---------------|------|
| US-1 | User story | Hold without judgment | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| US-2 | User story | No institutional backlash on SI | `companion_language_policy.py` `FORBIDDEN_PATTERNS` | `test_companion_language_policy.py` |
| US-3 | User story | Micro-steps not lectures | `emotional_safety_hub.py` prompts | manual / future SC |
| US-4 | User story | Private content not in VictoriaLogs | `app/logger.py` `_VICTORIA_EXCLUDED_LOG_TYPES` | alignment checker |
| SC-001 | Clinical | Suicidal ideation | `emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-002 | Clinical | Self-harm disclosure | `emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-003 | Clinical | Medication refusal sanitize | `emotional_safety_hub.py` `_check_response_safety` | `tests/clinical/test_crisis_scenarios.py` |
| SC-004 | Clinical | System error fallback | `error_handler.py` | `tests/clinical/test_crisis_scenarios.py` |
| SC-005 | Clinical | User demands hotline/ER | `companion_language_policy.py` | `tests/clinical/test_crisis_scenarios.py` |
| MET-1 | Metric | Crisis interception rate | `app/metrics/crisis_metrics.py` | `tests/metrics/test_crisis_metrics.py` |
| SEC-1 | Security | Secrets not in compose YAML | `docker-compose.yml` `${VAR}` | `tests/platform/test_compose_env.py` |
| SEC-2 | Security | pip-audit gate | `scripts/security/pip_audit_check.py` | CI `dependency-audit` |

## Planned (P3–P4)

| ID | Type | Requirement | Code (target) | Test (target) |
|----|------|-------------|---------------|---------------|
| SC-006 | Red team | Prompt injection hotline | orchestrator + hub | `tests/clinical/test_red_team_prompts.py` |
| SC-007 | Red team | Jailbreak institutional | hub | `tests/clinical/test_red_team_prompts.py` |
| SLO-3 | Performance | Crisis p95 < 5s | hub histogram | Grafana + load test |

## Maintenance

- Any new SC-* in `tests/clinical/crisis_scenarios.py` must add a row here before merge.
- PR template checklist references this file.
