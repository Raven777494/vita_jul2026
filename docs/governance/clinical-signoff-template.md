# Clinical Advisor Sign-Off Record (Template)

Version: 1.0 (P6-1)  
Use: Required when a PR changes `app/clinical/` or `tests/clinical/` (see `.github/PULL_REQUEST_TEMPLATE.md`)

**Store completed records outside this repository** (encrypted ops/clinical store per [../security/secrets-policy.md](../security/secrets-policy.md)). Link the record ID in the PR description; do not commit personal contact details or signed PDFs to git.

---

## Record header

| Field | Value |
|-------|-------|
| Sign-off ID | CLIN-SIGN-YYYY-MM-NNN |
| Date (UTC) | |
| PR / change reference | e.g. `#123` or release tag |
| Clinical advisor | Name (external record only) |
| Engineering reviewer | |
| Product owner (if consulted) | |

## Scope of change

| Path pattern | Changed | Notes |
|--------------|---------|-------|
| `app/clinical/` | yes / no | |
| `tests/clinical/` | yes / no | |
| `app/services/emotional_safety_hub.py` | yes / no | crisis path |
| User-facing prompts / orchestrator copy | yes / no | |
| Grafana / runbook clinical wording | yes / no | |

## Documents reviewed

| Document | Version reviewed | Reviewed |
|----------|------------------|----------|
| [../requirements/PRD.md](../requirements/PRD.md) | | [ ] |
| [../clinical/companion-language-guide.md](../clinical/companion-language-guide.md) | | [ ] |
| [../requirements/traceability-matrix.md](../requirements/traceability-matrix.md) | | [ ] |
| Relevant ADR (if architecture impact) | | [ ] |

## Clinical scenario regression (required)

Run before sign-off:

```powershell
python -m pytest tests/clinical/ -q
python scripts/governance/check_traceability.py
python app/tests/system_alignment_checker.py
```

| Scenario | ID | Pass | Notes |
|----------|-----|------|-------|
| Suicidal ideation | SC-001 | [ ] | |
| Self-harm disclosure | SC-002 | [ ] | |
| Medication refusal sanitize | SC-003 | [ ] | |
| System error fallback | SC-004 | [ ] | |
| Hotline/ER boundary | SC-005 | [ ] | |
| Prompt injection hotline | SC-006 | [ ] | |
| Jailbreak institutional override | SC-007 | [ ] | |
| DAN jailbreak hotline leak | SC-008 | [ ] | |
| Benign input poisoned LLM output | SC-009 | [ ] | |
| Orchestrator finalize injection block | SC-010 | [ ] | |

## Forbidden-pattern checklist

Confirm no new user-facing violations (see companion-language-guide):

- [ ] No hotline names or numbers (e.g. 2389)
- [ ] No ER / hospitalization / restraint language in user-visible text
- [ ] No patient labels or medication directives
- [ ] No user-visible escalation ("已通知同事", "通報", institutional referral)
- [ ] API errors do not instruct emergency calls

## Monitoring impact (if crisis path changed)

- [ ] `python scripts/observability/verify_p5_monitoring.py --skip-steady-state` passed in target env
- [ ] Escalation webhook drill considered (`scripts/observability/drill_escalation_webhook.py --dry-run`)

## Decision

| Outcome | Selected |
|---------|----------|
| **Approved** — merge / deploy allowed | [ ] |
| **Approved with conditions** — list below | [ ] |
| **Rejected** — do not merge | [ ] |

Conditions / follow-up (if any):

```
(free text — external record)
```

## Signatures (external store)

| Role | Signature / initials | Date |
|------|----------------------|------|
| Clinical advisor | | |
| Engineering lead | | |

---

## Related

- [RACI.md](RACI.md) — Clinical advisor **A** for companion language
- [execution-program.md](execution-program.md) P6-1, P6-2
- [prd-v1-clinical-approval-checklist.md](prd-v1-clinical-approval-checklist.md) — PRD v1.0 baseline (external)
- [tech-debt-register.md](tech-debt-register.md) — CD-002 closed P6-2; use per-PR template for ongoing changes
