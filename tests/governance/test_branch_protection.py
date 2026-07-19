"""Tests for branch protection and ops archive helpers."""

from __future__ import annotations

from pathlib import Path

from scripts.governance.apply_branch_protection import (
    REQUIRED_CHECKS,
    protection_payload,
)
from scripts.governance.verify_branch_protection import REQUIRED_CHECKS as VERIFY_CHECKS


def test_protection_payload_solo_has_zero_approvals() -> None:
    payload = protection_payload(solo=True)
    assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 0
    assert payload["allow_force_pushes"] is False
    assert payload["allow_deletions"] is False
    assert payload["required_status_checks"]["strict"] is True
    assert set(payload["required_status_checks"]["contexts"]) == set(REQUIRED_CHECKS)


def test_protection_payload_team_requires_one_approval() -> None:
    payload = protection_payload(solo=False)
    assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 1


def test_required_checks_match_ci_jobs() -> None:
    assert VERIFY_CHECKS == frozenset(REQUIRED_CHECKS)
    assert "test-and-alignment" in REQUIRED_CHECKS
    assert "dependency-audit" in REQUIRED_CHECKS


def test_ops_archive_script_and_gitignore() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts/ops/archive_ops_record.ps1").is_file()
    assert (root / "scripts/governance/apply_branch_protection.py").is_file()
    assert (root / "scripts/governance/verify_branch_protection.py").is_file()
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "_ops_archive/" in gitignore
