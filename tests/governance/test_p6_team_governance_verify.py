"""Tests for P6-1 team governance verification."""

from __future__ import annotations

from scripts.governance.verify_p6_team_governance import verify_p6_team_governance


def test_verify_p6_team_governance_passes_on_repo():
    errors = verify_p6_team_governance()
    assert errors == []
