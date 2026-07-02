# Branch Strategy

Version: 0.1 (P1)

## Branches

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready; protected; CI must pass |
| `develop` | Integration branch for next release |
| `feature/*` | Short-lived feature work |
| `fix/*` | Bug fixes |

## Workflow

1. Branch from `develop` (or `main` for hotfix)
2. Open PR to `develop`
3. CI green: clinical tests, alignment checker, pip-audit, compose config
4. Review (see PR template)
5. Merge to `develop`; release PR to `main`

## Hotfix

1. Branch from `main` as `fix/description`
2. PR to `main` and backport to `develop`

## Commit messages

Complete sentences; focus on why. Example: `Fix extension bootstrap false OK when CREATE EXTENSION fails silently.`

## Tags

Release tags `v2.x.y` on `main` after validation.

## Protected branch rules (recommended GitHub settings)

- Require PR before merge
- Require status checks: `test-and-alignment`, `dependency-audit`
- No force push to `main`
