# ADR-001: Single User-Facing Safety Path

Status: Accepted (P3-3)  
Date: 2026-07-03  
Deciders: Engineering (VITA Logic Engine)

## Context

VITA had parallel safety-related modules:

| Module | Role |
|--------|------|
| `EmotionalSafetyHub` | Crisis assessment, escalation, companion replies |
| `SafetyService` | Internal risk scoring, n8n webhook (never wired to main chat) |
| `Orchestrator` | Star pipeline, navigator, personality — LLM text could bypass policy |
| `IntelligentNavigator` | Fracture routing with `_get_safe_reply` fallbacks |
| `companion_language_policy` | Forbidden patterns and safe reply tiers |

Risk: LLM or navigator output could reach users without `validate_user_facing_text`.

## Decision

1. **Policy source of truth:** `app/clinical/companion_language_policy.py`
2. **User-facing gate (mandatory):** `app/clinical/user_facing_gate.py`  
   All orchestrator chat outcomes pass through `apply_user_facing_gate()` in `_finalize_turn_outcome`.
3. **Crisis hub path:** `EmotionalSafetyHub` remains the dedicated crisis pipeline (tests SC-001..010).
4. **SafetyService:** Internal-only (risk metadata, n8n). Must not emit user chat text.
5. **Safe fallbacks:** `_get_safe_reply()` uses `get_companion_reply()` then gate.

## Consequences

### Positive

- Single validation point before `result['text']` in orchestrator
- CI clinical tests + gate tests enforce non-institutional language
- Clear ADR for onboarding and audits

### Negative / follow-up

- Navigator direct callers outside orchestrator should also use gate (currently orchestrator wraps all API chat)
- `SafetyService` remains in codebase for future n8n integration; not deleted in P3-3
- P3-4 red-team tests (SC-006..010) merged; ongoing model prompt hardening (TD-004)

## Verification

```powershell
python -m pytest tests/clinical/test_red_team_prompts.py tests/clinical/ -q
python scripts/governance/check_traceability.py
```

## References

- `docs/architecture/safety-critical-path.md`
- `docs/requirements/traceability-matrix.md`
- `app/orchestrator.py` `_finalize_turn_outcome`, `_get_safe_reply`
