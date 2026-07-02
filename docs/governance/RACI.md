# RACI Matrix (VITA Governance)

Version: 0.1 (P6 template — assign names before production)

Legend: **R** = Responsible, **A** = Accountable, **C** = Consulted, **I** = Informed

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

## Named roles (fill before go-live)

| Role | Name | Contact |
|------|------|---------|
| Product owner | TBD | |
| Engineering lead | TBD | |
| Clinical advisor | TBD | |
| On-call primary | TBD | external runbook |

## Escalation

1. On-call (Ops **A**) — technical outage, deploy failure
2. Clinical advisor (**A** for language) — interception rate drop, policy test failure in production
3. Engineering lead — code fix and rollback execution

See `docs/governance/execution-program.md` P6-1.
