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

| Step | Module | SLO |
|------|--------|-----|
| User-facing gate | `app/clinical/user_facing_gate.py` | SLO-4 (interception via gate blocks) |
| Policy / forbidden patterns | `app/clinical/companion_language_policy.py` | SLO-4 |
| Orchestrator finalize | `app/orchestrator.py` `_finalize_turn_outcome` | SLO-2 / SLO-3 (latency by path label) |
| Orchestrator fallbacks | `app/orchestrator.py` `_get_safe_reply` | SLO-3 (crisis fast track) |
| Crisis hub | `app/services/emotional_safety_hub.py` | SLO-3 / SLO-4 |
| Navigator fallbacks | `app/services/fracture_map/intelligent_navigator.py` | SLO-3 |
| Internal risk / n8n (not chat) | `app/services/safety_service.py` | SLO-1 (availability of ops path) |
| Config defaults | `app/config.py` `DEFAULT_SAFE_REPLIES` | — |
| Chat latency metrics | `app/metrics/chat_latency_metrics.py` | SLO-2 / SLO-3 |
| Crisis counters | `app/metrics/crisis_metrics.py` | SLO-4 |

## End-to-end SLO map (crisis path)

| Stage | Path layer | SLO ID | Target | Measurement |
|-------|------------|--------|--------|-------------|
| Input risk scoring | Orchestrator / hub | SLO-3 | p95 < 5s | `vita_chat_processing_seconds{path="crisis"}` |
| Companion output gate | User-facing gate + policy | SLO-4 | interception >= 95% | `vita_crisis_interception_rate` |
| Internal escalation | private/crisis logs + notifier | SLO-1 | ops path available | health + webhook drill |
| Normal chat latency | Orchestrator normal path | SLO-2 | p95 < 3s | `vita_chat_processing_seconds{path="normal"}` |

See [../operations/slo.md](../operations/slo.md) for alert thresholds and review cadence.

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
