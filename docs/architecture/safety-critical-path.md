# Safety Critical Path

Version: 0.2 (P3-3 / ADR-001)

## User-visible path (companion layer)

```mermaid
flowchart TD
  IN[User message] --> ORCH[Orchestrator process_user_message]
  ORCH --> RISK[Emotion / session risk scoring]
  RISK -->|critical fast track| SAFE[_get_safe_reply critical]
  RISK -->|normal| PIPE[Navigator / LLM / Personality]
  PIPE --> DRAFT[Draft response text]
  SAFE --> GATE[apply_user_facing_gate]
  DRAFT --> FINAL[_finalize_turn_outcome]
  FINAL --> GATE
  GATE --> OUT[User sees text only]
```

Forbidden on `OUT`: hotlines, ER, hospitalization commands, patient labels, visible escalation notices.

Parallel crisis pipeline (hub tests / dedicated flows):

```mermaid
flowchart LR
  HIN[User input] --> HUB[EmotionalSafetyHub]
  HUB --> HPOL[companion_language_policy validate]
  HPOL --> HOUT[Companion reply]
```

## Internal path (operations layer)

```mermaid
flowchart TD
  RISK[Risk level 4-5] --> PLOG[private / crisis / critical logs]
  PLOG --> AUDIT[audit events]
  AUDIT --> NOTIFY[Notification hook optional]
  NOTIFY --> HUMAN[Human supervisor review]
  N8N[SafetyService n8n webhook] -.-> NOTIFY
```

`SafetyService` is internal-only; it does not produce user chat text (ADR-001).

## Code map

| Step | Module |
|------|--------|
| User-facing gate | `app/clinical/user_facing_gate.py` |
| Policy / forbidden patterns | `app/clinical/companion_language_policy.py` |
| Orchestrator finalize | `app/orchestrator.py` `_finalize_turn_outcome` |
| Orchestrator fallbacks | `app/orchestrator.py` `_get_safe_reply` |
| Crisis hub | `app/services/emotional_safety_hub.py` |
| Navigator fallbacks | `app/services/fracture_map/intelligent_navigator.py` |
| Internal risk / n8n (not chat) | `app/services/safety_service.py` |
| Config defaults | `app/config.py` `DEFAULT_SAFE_REPLIES` |

## Verification

- `pytest tests/clinical/` (SC-001..010: crisis + red-team)
- `tests/clinical/test_orchestrator_companion_gate.py`
- `tests/clinical/test_red_team_prompts.py`

## Red-team coverage (P3-4)

| ID | Attack vector | Mitigation under test |
|----|---------------|---------------------|
| SC-006 | Direct hotline injection in user prompt + poisoned LLM | Hub `_check_response_safety` + gate |
| SC-007 | Institutional SYSTEM OVERRIDE jailbreak | Hub fallback + gate |
| SC-008 | DAN / English hotline jailbreak | Hub fallback + gate |
| SC-009 | Benign user input, poisoned LLM output | Hub sanitization |
| SC-010 | Injection via orchestrator finalize path | `apply_user_facing_gate` in `_finalize_turn_outcome` |

User-visible mitigation layers (defense in depth):

1. Companion prompt constraints in `EmotionalSafetyHub._build_companion_prompt`
2. Post-LLM `validate_user_facing_text` in hub and gate
3. Orchestrator `_finalize_turn_outcome` gate on all chat output
- `docs/architecture/adr-001-safety-path.md`
- `docs/clinical/companion-language-guide.md`
