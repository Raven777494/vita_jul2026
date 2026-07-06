"""Tests for P6-2 requirements signoff verification."""

from __future__ import annotations

from scripts.governance.verify_p6_requirements_signoff import verify_p6_requirements_signoff


def test_verify_p6_requirements_signoff_passes_after_cd002_closed():
    errors = verify_p6_requirements_signoff()
    assert errors == []
