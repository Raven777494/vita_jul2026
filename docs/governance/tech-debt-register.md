# Technical Debt Register

Version: 0.1 (P1)  
Review: monthly or each release candidate

| ID | Item | Risk | Priority | Target | Notes |
|----|------|------|----------|--------|-------|
| TD-001 | AGE graph vs relational memory_graph dual model | Medium | P2 | Q3 | App uses SQL memory_graph; AGE vita_memory_graph provisioned but underused |
| TD-002 | Alembic migrations not primary | Medium | P2 | In progress | Baseline stamp `20260702_0001`; see docs/database/migrations.md |
| TD-003 | execute_update swallows SQL errors | Low | P2 | Q2 | Returns 0 on failure; fixed for extensions verify; audit other callers |
| TD-004 | LLM prompt injection hardening | High | P1 | Ongoing | Safety hub heuristics; add red-team clinical tests |
| TD-005 | Notification hook stub | Medium | P2 | Q3 | `_send_escalation_notifications` logs only |
| TD-006 | docker-compose dev secrets in YAML | Medium | P1 | Closed P2-B | Secrets moved to `config/.env.compose`; compose uses `${VAR}` only; deploy.yml skeleton |
| TD-007 | Dependency CVE tracking (pip-audit CI gate) | Medium | P1 | Closed P1 | Green gate via fastapi 0.135.0 / starlette 1.3.1 / python-jose 3.5.0 |
| TD-008 | Monitoring dashboards not codified | Low | P2 | Partial P2-C | Crisis interception metrics + Grafana/LogsQL alerts in repo |

## Clinical debt (linked)

| ID | Item | Risk | Priority | Target | Notes |
|----|------|------|----------|--------|-------|
| CD-001 | Expand clinical scenario test suite beyond language policy | High | P2 | Partial P3-2 | SC-001..005 + traceability CI gate |
| CD-002 | Clinical advisor sign-off process | Medium | P2 | P6 | PRD v1.0 engineering baseline approved; formal sign-off pending |

## Related

- [execution-program.md](execution-program.md) — roadmap to close all 12 governance gaps (P3–P6)
- [RACI.md](RACI.md)

## Closed (P0)

| ID | Item | Closed |
|----|------|--------|
| TD-P0-001 | User-facing hotline in crisis replies | P0 companion policy |
| TD-P0-002 | No CI pipeline | P0 `.github/workflows/ci.yml` |
| TD-P0-003 | False OK on failed CREATE EXTENSION | P1 db_manager verify |
| TD-P1-001 | pip-audit CI gate failing (starlette/pyasn1/dotenv) | P1 dep upgrades 2026-06-30 |
