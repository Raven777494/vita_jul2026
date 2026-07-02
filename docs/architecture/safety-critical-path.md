# Safety Critical Path

Version: 0.1 (P1)

## User-visible path (companion layer)

```mermaid
flowchart TD
  IN[User message] --> HUB[Emotional Safety Hub]
  HUB --> RISK[Risk assessment]
  RISK -->|level 1-3| REPLY[Companion reply]
  RISK -->|level 4-5| HOLD[Hold + ground + recall resources]
  HOLD --> REPLY
  REPLY --> OUT[User sees text only]
```

Forbidden on `OUT`: hotlines, ER, hospitalization commands, patient labels, visible escalation notices.

## Internal path (operations layer)

```mermaid
flowchart TD
  RISK[Risk level 4-5] --> PLOG[private / crisis / critical logs]
  PLOG --> AUDIT[audit events]
  AUDIT --> NOTIFY[Notification hook optional]
  NOTIFY --> HUMAN[Human supervisor review]
```

Internal escalation does not change user-visible wording to institutional referral.

## Code map

| Step | Module |
|------|--------|
| Risk scoring | `app/services/emotional_safety_hub.py` |
| Safe replies | `app/clinical/companion_language_policy.py` |
| Navigator safety mode | `app/services/fracture_map/intelligent_navigator.py` |
| Orchestrator fallback | `app/orchestrator.py` `_get_safe_reply` |
| Config defaults | `app/config.py` `DEFAULT_SAFE_REPLIES` |

## Verification

- `pytest tests/clinical/`
- `docs/clinical/companion-language-guide.md`
- `docs/operations/crisis-playbook.md`
