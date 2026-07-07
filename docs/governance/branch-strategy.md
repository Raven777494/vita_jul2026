# Branch Strategy

Version: 0.2 (B-zone go-live)

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

Release tags use [Semantic Versioning](https://semver.org/) on **`main`** after validation:

| Pattern | Example | When |
|---------|---------|------|
| `vMAJOR.MINOR.PATCH` | `v1.0.0` | Production release on `main` |
| `vMAJOR.MINOR.PATCH-rc.N` | `v1.0.0-rc.1` | Release candidate on `develop` before merge to `main` |
| `vMAJOR.MINOR.PATCH-hotfix.N` | `v1.0.1-hotfix.1` | Emergency patch from `main` |

### Release tagging procedure

1. Confirm CI green on target branch (`develop` for RC, `main` for production).
2. Run master verification from [governance-matrix.md](governance-matrix.md).
3. Merge release PR (`develop` -> `main`) for production; keep RC tags on `develop` only.
4. Create annotated tag on the release commit:

```powershell
git checkout main
git pull origin main
git tag -a v1.0.0 -m "VITA 1.0.0 production release"
git push origin v1.0.0
```

5. Record tag, commit SHA, and clinical sign-off ID in external release archive (P6-1.4).

**First release candidates:**

| Tag | Commit context |
|-----|----------------|
| `v1.0.0-rc.1` | B-zone go-live engineering complete |
| `v1.0.0-rc.2` | C-zone CI green (branch protection + secrets verification) |

Create RC tags on `develop` after CI green:

```powershell
git tag -a v1.0.0-rc.2 -m "VITA 1.0.0-rc.2 — C-zone CI green"
git push origin v1.0.0-rc.2
```

## Protected branch rules (recommended GitHub settings)

Configure per [github-setup-c-zone.md](../operations/github-setup-c-zone.md) (C-zone go-live **0.2**).

| Branch | Required checks |
|--------|-----------------|
| `main` | `test-and-alignment`, `dependency-audit` |
| `develop` | `test-and-alignment`, `dependency-audit` |

- Require PR before merge
- No force push
- Include administrators (recommended)

## Related

- [repo-bootstrap.md](repo-bootstrap.md) — P3-1 full git adoption and GitHub remote setup
- [execution-program.md](execution-program.md) — governance roadmap P3–P6
- [go-live-checklist.md](go-live-checklist.md) — pre-production gate
- [github-setup-c-zone.md](../operations/github-setup-c-zone.md) — branch protection + Encrypted Secrets
- [deploy-d-zone.md](../operations/deploy-d-zone.md) — staging deploy + monitoring drills
