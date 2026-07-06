"""Tests for missed interception investigation script."""

from __future__ import annotations

from scripts.observability.investigate_missed_interceptions import _classify_event


def test_classify_pytest_u2_s2():
    row = {"user_id": "u2", "session_id": "s2", "source": ""}
    assert _classify_event(row) == "pytest_crisis_metrics_test"


def test_classify_production_safety_hub():
    row = {"user_id": "real-user", "session_id": "sess-1", "source": "safety_hub"}
    assert _classify_event(row) == "production_safety_hub"
