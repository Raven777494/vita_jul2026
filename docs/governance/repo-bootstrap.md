# Git repository bootstrap (P3-1)

Version: 1.0

One-time steps to adopt full version control and branch protection for VITA (engine7b).

## 1. Local repository (done in P3-1)

```powershell
cd D:\Desktop\engine7b

# Verify ignored secrets are not tracked
python scripts/security/scan_secrets.py

# Full tree (respects .gitignore)
git add -A
git status

# Primary branch name
git branch -M main
git checkout -b develop
git checkout main
```

## 2. Create GitHub remote

Replace `YOUR_ORG` and `YOUR_REPO`:

```powershell
git remote add origin https://github.com/YOUR_ORG/YOUR_REPO.git
git push -u origin main
git push -u origin develop
```

Set **default branch** to `main` in GitHub: Settings -> General -> Default branch.

## 3. Branch protection (GitHub Settings -> Branches)

### `main`

| Rule | Value |
|------|-------|
| Require pull request | Yes |
| Required status checks | `test-and-alignment`, `dependency-audit` |
| Require branches up to date | Yes |
| Restrict force push | Yes |
| Restrict deletions | Yes |

### `develop`

| Rule | Value |
|------|-------|
| Require pull request | Yes |
| Required status checks | `test-and-alignment`, `dependency-audit` |
| Restrict force push | Yes |

## 4. GitHub Encrypted Secrets (Actions)

Repository Settings -> Secrets and variables -> Actions. Required for deploy workflow:

See `docs/operations/deploy.md` for the full list (`POSTGRES_PASSWORD`, `JWT_SECRET`, etc.).

Never commit `config/.env.compose` or production values.

## 5. Release tag (after first green CI on main)

```powershell
git checkout main
git pull
git tag -a v2.0.0-governance-baseline -m "Governance baseline: P0-P2 + P3-1 full repo"
git push origin v2.0.0-governance-baseline
```

## 6. CI security rules (mandatory)

1. Only Verified Creator GitHub Actions (`actions/*` with blue badge).
2. Pin version tags (`@v4`, `@v5`); never `@main` or `@master`.
3. No secrets in workflow YAML; use `${{ secrets.NAME }}` only.

Current workflows: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`.

## 7. Pre-push checklist

```powershell
python scripts/security/scan_secrets.py
python -m pytest tests/clinical/ tests/metrics/ tests/platform/ -q --tb=short
docker compose --env-file config/.env.compose.ci config --quiet
```

## Related

- `docs/governance/branch-strategy.md`
- `docs/governance/execution-program.md` (P3-1)
