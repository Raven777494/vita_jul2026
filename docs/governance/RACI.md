# RACI Matrix (VITA Governance)

Version: 1.0 (P6-1)  
Status: Active template — **named roster stored outside repo** (see [Named roles](#named-roles))

Legend: **R** = Responsible, **A** = Accountable, **C** = Consulted, **I** = Informed

## Activity matrix

| Activity | Product owner | Engineering | Clinical advisor | Operations / on-call |
|----------|---------------|-------------|------------------|----------------------|
| PRD and user story changes | A | R | C | I |
| Companion language / crisis copy | C | R | **A** | I |
| Architecture decision (ADR) | C | **A** | C | I |
| Schema / migration change | C | **A** | I | C |
| Security incident (S1/S2) | I | R | C | **A** |
| Production deploy | I | R | C | **A** |
| CI/CD and secrets rotation | I | **A** | I | R |
| Clinical scenario test changes | C | R | **A** | I |
| Monitoring alert tuning | I | R | C | **A** |
| Tech debt prioritization | **A** | R | C | I |
| Post-incident review | C | R | C | **A** |

## Named roles

Personal names and direct contact details **must not** be committed to this repository ([../security/secrets-policy.md](../security/secrets-policy.md)). Maintain a single external roster (encrypted ops store) and reference it here.

| Role | In-repo duty | External roster field | Status |
|------|--------------|----------------------|--------|
| Product owner | PRD priority, user impact comms | `product_owner` | Assign before go-live |
| Engineering lead | Code, deploy execution, rollback | `engineering_lead` | Assign before go-live |
| Clinical advisor | Companion language **A**, SC sign-off | `clinical_advisor` | Assign before go-live |
| On-call primary | S1/S3 outage, alert ack | `on_call_primary` | See [../operations/on-call.md](../operations/on-call.md) |

**External roster location (fill before production):**

| Field | Value |
|-------|-------|
| Store name | TBD — e.g. org encrypted drive / password manager |
| Document ID | TBD — e.g. OPS-ROSTER-001 |
| Last updated | TBD |

## Clinical sign-off workflow (P6-1)

1. PR touches `app/clinical/` or `tests/clinical/` → clinical advisor sign-off **required** (`.github/PULL_REQUEST_TEMPLATE.md`).
2. Complete [clinical-signoff-template.md](clinical-signoff-template.md) in external store.
3. Link sign-off ID (e.g. `CLIN-SIGN-2026-07-001`) in PR description.
4. Archive sign-off with production release record (P6-1.4 — external).

Verify repo deliverables:

```powershell
python scripts/governance/verify_p6_team_governance.py
```

## Escalation

1. On-call (Ops **A**) — technical outage, deploy failure ([../operations/on-call.md](../operations/on-call.md))
2. Clinical advisor (**A** for language) — interception rate drop, policy test failure ([../operations/incident.md](../operations/incident.md) S2)
3. Engineering lead — code fix and rollback execution

## Related

- [execution-program.md](execution-program.md) P6-1
- [clinical-signoff-template.md](clinical-signoff-template.md)
- [prd-v1-clinical-approval-checklist.md](prd-v1-clinical-approval-checklist.md)
- [governance-matrix.md](governance-matrix.md) governance #11
