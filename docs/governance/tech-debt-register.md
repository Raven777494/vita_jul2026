# Technical Debt Register

Version: 1.0 (P5-3)  
Review: monthly or each release candidate  
Governance: [#12 Technical debt](../governance/execution-program.md#p5-3-technical-debt-program-governance-12)

| ID | Item | Risk | Priority | Target | Governance | Phase | Notes |
|----|------|------|----------|--------|------------|-------|-------|
| TD-001 | AGE graph vs relational memory_graph dual model | Medium | P2 | Closed P4-4 | #7 | P4 | ADR-002: primary writes = gsw_eternal_echoes + memory_graph (relational); AGE vita_memory_graph read-only reserve; alignment in app/governance/memory_model_alignment.py |
| TD-002 | Alembic migrations not primary | Medium | P2 | Closed P4-1 | #7 | P4 | Primary policy in docs/database/migrations.md; baseline `20260702_0001` |
| TD-003 | execute_update swallows SQL errors | Low | P2 | Closed P5-3 | #12 | P5 | `DatabaseUpdateError` raised on failure; audit in scripts/governance/audit_execute_update.py |
| TD-004 | LLM prompt injection hardening | High | P1 | Closed P4-2 | #4 | P4 | Input sanitizer + audit metadata; red-team SC-006..010; see docs/security/prompt-injection-mitigations.md |
| TD-005 | Notification hook stub | Medium | P2 | Closed P4-2 | #10 | P4 | `app/services/escalation_notifier.py`; `ESCALATION_WEBHOOK_URL` from env |
| TD-006 | docker-compose dev secrets in YAML | Medium | P1 | Closed P2-B | #4 | P2 | Secrets moved to `config/.env.compose`; compose uses `${VAR}` only; deploy.yml skeleton |
| TD-007 | Dependency CVE tracking (pip-audit CI gate) | Medium | P1 | Closed P1 | #6 | P1 | Green gate via fastapi 0.135.0 / starlette 1.3.1; removed unused python-jose (ecdsa CVE-2024-23342) |
| TD-008 | Monitoring dashboards not codified | Low | P2 | Closed P5-1 | #9 | P5 | Grafana crisis/SLO dashboards + VM scrape + alert routing + verify_p5_monitoring.py |
| TD-009 | Deploy CD host registry optional | Low | P3 | Closed B-go-live | #8 | P3 | Accepted: SSH image stream is primary deploy path (`deploy.yml`); optional container registry push deferred post-go-live (see deploy.md) |

## Clinical debt (linked)

| ID | Item | Risk | Priority | Target | Governance | Phase | Notes |
|----|------|------|----------|--------|------------|-------|-------|
| CD-001 | Expand clinical scenario test suite beyond language policy | High | P2 | Closed P3-4 | #3 | P3 | SC-001..010 + traceability CI gate |
| CD-002 | Clinical advisor sign-off process | Medium | P2 | Closed P6-2 | #1/#11 | P6 | PR/signoff templates, PRD Approved v1.0, companion freeze; external PRD checklist at go-live |

## Review log

Monthly review ritual (P5-3). Record decisions here; detailed incident notes stay outside repo.

| Date | Reviewer | Open TDs / CD | Actions |
|------|----------|---------------|---------|
| 2026-07-06 | Engineering | TD-009 | Closed TD-003 (execute_update audit + DatabaseUpdateError); confirmed TD-008 closed P5-1; added governance/phase columns; next review 2026-08-01 |
| 2026-07-07 | Engineering | TD-009 | Closed CD-002 (P6-1/P6-2 sign-off process); PRD Approved v1.0; companion guide forbidden-pattern freeze |
| 2026-07-08 | Engineering | — | Closed TD-009 (SSH stream deploy accepted primary); B-zone: erasure API, SLO labels, coverage gate, release tag policy |

### Review checklist

1. All **High** priority open items have owner and target date in Target column.
2. Each open TD links to a governance item (#1–#12) and phase (P0–P6).
3. Run `python scripts/governance/verify_p5_tech_debt.py` before release candidate.
4. Run `python scripts/governance/audit_execute_update.py` after any new `execute_update` caller.

## Related

- [execution-program.md](execution-program.md) — roadmap to close all 12 governance gaps (P3–P6)
- [governance-matrix.md](governance-matrix.md) — completion percentages
- [RACI.md](RACI.md)
- [clinical-signoff-template.md](clinical-signoff-template.md)

## Closed (P0)

| ID | Item | Closed |
|----|------|--------|
| TD-P0-001 | User-facing hotline in crisis replies | P0 companion policy |
| TD-P0-002 | No CI pipeline | P0 `.github/workflows/ci.yml` |
| TD-P0-003 | False OK on failed CREATE EXTENSION | P1 db_manager verify |
| TD-P1-001 | pip-audit CI gate failing (starlette/pyasn1/dotenv) | P1 dep upgrades 2026-06-30 |
