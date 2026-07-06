"""Tests for P5-3 tech debt verification script."""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.governance.verify_p5_tech_debt import verify_register


SAMPLE_REGISTER = """# Technical Debt Register

| ID | Item | Risk | Priority | Target | Notes |
|----|------|------|----------|--------|-------|
| TD-003 | execute_update | Low | P2 | Closed P5-3 | Raises DatabaseUpdateError |

## Review log

| Date | Reviewer | Open TDs | Actions |
|------|----------|----------|---------|
| 2026-07-06 | Engineering | TD-009 | Closed TD-003 |
"""


def test_verify_register_passes_with_closed_td003_and_review_log():
    errors = verify_register(
        SAMPLE_REGISTER,
        now=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )
    assert errors == []


def test_verify_register_fails_without_review_log():
    content = "| TD-003 | x | Low | P2 | Closed P5-3 | y |"
    errors = verify_register(content, now=datetime(2026, 7, 6, tzinfo=timezone.utc))
    assert any("Review log" in e for e in errors)
