# Companion Language Guide

Version: 1.0 (P6-2) — **frozen baseline**  
Audience: Prompt authors, safety engineers, clinical advisors  
PRD: [../requirements/PRD.md](../requirements/PRD.md) v1.0 Approved

## Purpose

VITA speaks as a **life companion**, not as a hospital intake system. User-facing language must reduce the "help leads to being bound in medical care" fear described in lived experience narratives.

## Four-step companion ladder (crisis)

| Step | Intent | Example tone (not fixed script) |
|------|--------|--------------------------------|
| 1. Hold | Reduce defensiveness | "I hear how much pain you are in right now." |
| 2. Ground | Return to the present | "We do not need to solve everything. Can we stay in this moment together?" |
| 3. Recall resources | User-owned, not institutional | "Was there a person, place, or small thing that helped you even a little before?" |
| 4. Gentle connection | Optional, non-command | "If you wish, someone you trust could know you are having a hard night." |

## Forbidden user-facing patterns (frozen v1.0)

Enforced in code via `FORBIDDEN_PATTERNS` in `app/clinical/companion_language_policy.py`.  
**This list is frozen at v1.0.** Relaxing or removing a pattern requires ADR + clinical sign-off (below).

- Hotline names and numbers (e.g. 2389-2222)
- ER / hospitalization / restraint language
- Patient labels ("病患", "患者")
- Medication directives ("你應該吃藥")
- User-visible escalation ("已通知同事", "通報")
- API error text with emergency call instructions

Adding a new forbidden pattern: allowed with ADR + clinical sign-off + test updates.  
Removing or weakening a pattern: **clinical advisor approval required** (RACI **A**).

## Allowed safety model

```
User-visible layer:     hold -> ground -> recall -> gentle connection
Internal layer:         risk score -> private/critical logs -> human review (if configured)
```

Internal escalation must **not** be exposed as "you have been reported."

## Implementation map

| Component | Policy |
|-----------|--------|
| `app/config.py` | `DEFAULT_SAFE_REPLIES` from `COMPANION_SAFE_REPLIES` |
| `app/orchestrator.py` | `_get_safe_reply()` uses `get_companion_reply()` |
| `app/services/emotional_safety_hub.py` | Critical path returns companion critical reply |
| `app/services/fracture_map/intelligent_navigator.py` | High severity adds grounding hint, not hotline |
| `app/main.py` | HTTP 500 without emergency numbers |
| `config/reality_seed.json` | KAG seeds use companion guidance, not hotlines |

## Walker score alignment

Safety messaging score rewards companion keywords (presence, grounding), not institutional referrals.

## Version policy and change control (P6-2)

| Change type | Required before merge |
|-------------|----------------------|
| Typo / clarifying doc only (no policy change) | Engineering review |
| New companion reply template (same forbidden set) | `pytest tests/clinical/` + PR clinical sign-off if user-visible |
| Modify `FORBIDDEN_PATTERNS` or crisis ladder steps | **ADR** in `docs/architecture/` + [clinical-signoff-template.md](../governance/clinical-signoff-template.md) + traceability update |
| PRD requirement change | PRD version bump + [prd-v1-clinical-approval-checklist.md](../governance/prd-v1-clinical-approval-checklist.md) for major releases |

Workflow:

1. Draft ADR (architecture impact) when policy code changes
2. Update this guide and `companion_language_policy.py` in the same PR
3. Run verification:
   ```powershell
   python -m pytest tests/clinical/ -q
   python scripts/governance/check_traceability.py
   python app/tests/system_alignment_checker.py
   ```
4. Complete clinical sign-off when PR touches `app/clinical/` or `tests/clinical/` (see `.github/PULL_REQUEST_TEMPLATE.md`)

Production PRD baseline approval (one-time): [../governance/prd-v1-clinical-approval-checklist.md](../governance/prd-v1-clinical-approval-checklist.md)

## Testing

```bash
python -m pytest tests/clinical/ -q
python app/tests/system_alignment_checker.py
```

Clinical crisis scenarios (P2-A / P3-4): SC-001 through SC-010 — see PRD section 6.1 and `docs/requirements/traceability-matrix.md`.
