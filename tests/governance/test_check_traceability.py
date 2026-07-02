"""Tests for governance traceability checker (P3-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.governance.check_traceability import check_traceability

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIX = PROJECT_ROOT / "docs" / "requirements" / "traceability-matrix.md"


def test_traceability_matrix_passes() -> None:
    errors = check_traceability(MATRIX)
    assert errors == [], errors


def test_checker_fails_when_sc_missing_from_matrix(tmp_path: Path) -> None:
    broken = tmp_path / "matrix.md"
    broken.write_text(
        """
## Active requirements

| ID | Type | Requirement (summary) | Code | Test |
|----|------|----------------------|------|------|
| US-1 | User story | x | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| US-2 | User story | x | `app/clinical/companion_language_policy.py` | `tests/clinical/test_crisis_scenarios.py` |
| US-3 | User story | x | `app/services/emotional_safety_hub.py` | `tests/clinical/test_crisis_scenarios.py` |
| US-4 | User story | x | `app/logger.py` | `tests/clinical/test_private_log_isolation.py` |
| P0-1 | Success metric | x | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| P0-2 | Success metric | x | `.github/workflows/ci.yml` | `CI:test-and-alignment` |
| P0-3 | Success metric | x | `app/clinical/companion_language_policy.py` | `tests/clinical/test_companion_language_policy.py` |
| MET-1 | Metric | x | `app/metrics/crisis_metrics.py` | `tests/metrics/test_crisis_metrics.py` |
| SEC-1 | Security | x | `docker-compose.yml` | `tests/platform/test_compose_env.py` |
| SEC-2 | Security | x | `scripts/security/pip_audit_check.py` | `CI:dependency-audit` |

## Planned
""",
        encoding="utf-8",
    )
    errors = check_traceability(broken)
    assert any("SC-001" in e or "missing from Active matrix" in e for e in errors)
