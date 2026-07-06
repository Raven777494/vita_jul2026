# PRD v1.0 Clinical Approval Checklist (External Record)

Version: 1.0 (P6-2)  
Use: Final clinical sign-off for `docs/requirements/PRD.md` v1.0 before production go-live.

**Complete this checklist in external clinical/ops storage.** Link the record ID in release notes; do not commit advisor signatures to git.

---

## Record header

| Field | Value |
|-------|-------|
| Record ID | CLIN-SIGN-PRD-v1-001 |
| Date (UTC) | |
| PRD version | 1.0 (P6-2) |
| Clinical advisor | Name (external only) |
| Engineering lead | |

## Documents reviewed

| Document | Path | Reviewed |
|----------|------|----------|
| PRD v1.0 | `docs/requirements/PRD.md` | [ ] |
| Companion language guide v1.0 | `docs/clinical/companion-language-guide.md` | [ ] |
| Traceability matrix | `docs/requirements/traceability-matrix.md` | [ ] |
| Crisis playbook (internal) | `docs/operations/crisis-playbook.md` | [ ] |

## Automated verification (engineering attestation)

Confirm engineering ran before clinical review:

```powershell
python scripts/governance/check_traceability.py
python scripts/governance/verify_p6_requirements_signoff.py
python -m pytest tests/clinical/ -q
python app/tests/system_alignment_checker.py
```

| Check | Pass |
|-------|------|
| Traceability 100% (SC-001..010 in matrix) | [ ] |
| P6-2 requirements signoff verify | [ ] |
| Clinical test suite | [ ] |
| Alignment checker 100% | [ ] |

## User stories (US-1..US-4)

| ID | Summary | Accept |
|----|---------|--------|
| US-1 | Hold without judgment | [ ] |
| US-2 | No institutional backlash on suicidal ideation | [ ] |
| US-3 | Micro-steps over lectures | [ ] |
| US-4 | Private content not in VictoriaLogs | [ ] |

## Clinical scenarios (SC-001..SC-010)

| ID | Type | Accept |
|----|------|--------|
| SC-001 | Suicidal ideation | [ ] |
| SC-002 | Self-harm disclosure | [ ] |
| SC-003 | Medication refusal sanitize | [ ] |
| SC-004 | System error fallback | [ ] |
| SC-005 | Hotline/ER boundary | [ ] |
| SC-006 | Prompt injection hotline | [ ] |
| SC-007 | Jailbreak institutional override | [ ] |
| SC-008 | DAN jailbreak hotline leak | [ ] |
| SC-009 | Poisoned LLM output | [ ] |
| SC-010 | Orchestrator injection block | [ ] |

## Forbidden-pattern freeze acknowledged

Clinical advisor confirms understanding of frozen baseline in companion-language-guide v1.0:

- [ ] No hotline/ER/hospitalization language in user-visible layer
- [ ] Changes to forbidden patterns require ADR + clinical sign-off (documented policy)
- [ ] Internal escalation must not appear as user-visible reporting

## Decision

| Outcome | Selected |
|---------|----------|
| **PRD v1.0 approved for production** | [ ] |
| **Approved with conditions** | [ ] |
| **Not approved** | [ ] |

Conditions:

```
(external)
```

## Signatures (external store)

| Role | Initials / signature | Date |
|------|----------------------|------|
| Clinical advisor | | |
| Product owner | | |
| Engineering lead | | |

---

## Related

- [clinical-signoff-template.md](clinical-signoff-template.md) — per-PR sign-off
- [RACI.md](RACI.md) — Clinical advisor **A** for companion language
- [tech-debt-register.md](tech-debt-register.md) — CD-002 closed when process + this record complete
