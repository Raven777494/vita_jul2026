## Summary

<!-- What changed and why (1-3 sentences) -->

## Type

- [ ] Feature
- [ ] Bug fix
- [ ] Security
- [ ] Documentation
- [ ] Clinical / companion language

## Checklist

- [ ] CI passes locally or on PR (`test-and-alignment`, `dependency-audit`)
- [ ] Traceability matrix updated if SC-* or US-* requirements changed (`docs/requirements/traceability-matrix.md`)
- [ ] `python scripts/governance/check_traceability.py` passes
- [ ] No secrets in code or workflow YAML (`python scripts/security/scan_secrets.py`)
- [ ] User-facing crisis text reviewed against `docs/clinical/companion-language-guide.md`
- [ ] If DB/schema change: `init-db/` or migration documented in PR
- [ ] Tech debt register updated if applicable (`docs/governance/tech-debt-register.md`)

## Clinical advisor sign-off (required if clinical paths changed)

**Required when this PR modifies any file under `app/clinical/` or `tests/clinical/`**, or changes user-facing crisis/companion copy in the safety hub, orchestrator, or clinical policy tests.

- [ ] This PR does **not** touch clinical paths (check and skip section below)
- [ ] Clinical paths changed — all items below completed:
  - [ ] `python -m pytest tests/clinical/ -q` passed
  - [ ] Clinical advisor reviewed forbidden-pattern impact
  - [ ] Sign-off record completed using `docs/governance/clinical-signoff-template.md`
  - [ ] Sign-off ID linked here: `CLIN-SIGN-YYYY-MM-NNN` (stored **outside repo**)

If unsure whether sign-off is required, treat as required and consult [docs/governance/RACI.md](docs/governance/RACI.md) (Clinical advisor **A** for companion language).

## Security (if applicable)

- [ ] Threat model impact considered (`docs/security/threat-model.md`)
- [ ] pip-audit clean or exception documented

## Test plan

<!-- How reviewer can verify -->
