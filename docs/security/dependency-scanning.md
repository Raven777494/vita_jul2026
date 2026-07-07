# Dependency Scanning

Version: 0.1 (P1)

## Tool

**pip-audit** (PyPI) scans pinned dependencies against the Python Packaging Advisory Database.

We run pip-audit via shell script — **no third-party GitHub Marketplace Actions** — to satisfy Verified Creator-only CI policy.

## Scope

| File | Purpose |
|------|---------|
| `requirements-audit.txt` | Pinned core runtime packages scanned in CI |
| `requirements.txt` | Full install list (includes llama-cpp-python, chromadb, unpinned redis) |

Excluded from automated audit (documented):

- `llama-cpp-python[server]` — source build; Windows long-path failures during pip-audit resolve
- `sentence-transformers`, `chromadb` — heavy transitive trees; manual review cadence
- Unpinned: `redis`, `pgvector`, `psutil`, `pytest-asyncio` — pin in future hardening

## CI

Workflow: `.github/workflows/ci.yml` job `dependency-audit`

Steps:

1. `actions/checkout@v4` (Verified)
2. `actions/setup-python@v5` (Verified)
3. `pip install -r requirements-dev.txt`
4. `python scripts/security/pip_audit_check.py` (defaults to `requirements-audit.txt`)

## Local

```powershell
python scripts/security/pip_audit_check.py
python scripts/security/pip_audit_check.py --requirements requirements-audit.txt
```

Optional strict mode (fail on unpinned requirements):

```powershell
python scripts/security/pip_audit_check.py --strict
```

## Remediation workflow

1. Read pip-audit advisory ID and affected package
2. Upgrade pinned version in `requirements.txt` and `requirements-audit.txt`
3. Re-run tests and pip-audit
4. If upgrade blocked, document exception in this file with expiry date and compensating control

## Resolved (P1, 2026-06-30)

| Advisory | Package | Resolution |
|----------|---------|------------|
| GHSA-mf9w-mj56-hr94 | python-dotenv 1.2.1 | Upgraded to 1.2.2 |
| GHSA-jr27-m4p2-rc6r | pyasn1 0.4.8 (via python-jose) | python-jose 3.5.0 + pyasn1 0.6.3 |
| PYSEC-2026-161/248/249, GHSA-wqp7-x3pw-xc5r, GHSA-x746-7m8f-x49c | starlette 0.52.1 | fastapi 0.135.0 + starlette 1.3.1 |
| PYSEC-2024-1325 / CVE-2024-23342 | ecdsa 0.19.2 (via python-jose) | Removed unused `python-jose` + `pyasn1` from requirements (2026-07-08); VITA auth uses HS256 API key only |

## Active exceptions

| Advisory | Package | Reason deferred | Expiry | Compensating control |
|----------|---------|-----------------|--------|---------------------|
| (none) | — | — | — | — |

## Exception template (historical)

| Advisory | Package | Reason deferred | Expiry | Compensating control |
|----------|---------|-----------------|--------|---------------------|
| (example) | urllib3 | Transitive via X; no fix on 3.11 yet | 2026-09-01 | Network isolation |

## Related files

- `requirements-dev.txt` — pip-audit pin
- `scripts/security/pip_audit_check.py` — CI entrypoint
- `docs/operations/github-setup-c-zone.md` — branch protection + secrets (C-zone)
