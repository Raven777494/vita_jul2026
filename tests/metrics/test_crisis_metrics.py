"""Tests for crisis interception metrics (P2-C)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from app.metrics.crisis_metrics import (
    CrisisSignalSnapshot,
    crisis_interception_rate,
    is_crisis_signal,
    record_crisis_interception_outcome,
    reset_crisis_metrics_for_tests,
)


@dataclass
class _FakeRisk:
    risk_level: int
    crisis_keywords: List[str]
    suicidal_indicators: int = 0
    self_harm_indicators: int = 0


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_crisis_metrics_for_tests()
    yield
    reset_crisis_metrics_for_tests()


def test_is_crisis_signal_by_risk_level():
    assert is_crisis_signal(CrisisSignalSnapshot(risk_level=3, crisis_keywords=()))
    assert not is_crisis_signal(CrisisSignalSnapshot(risk_level=2, crisis_keywords=()))


def test_is_crisis_signal_by_keywords():
    snap = CrisisSignalSnapshot(risk_level=1, crisis_keywords=("想死",))
    assert is_crisis_signal(snap)


def test_record_intercepted_increments_rate():
    risk = _FakeRisk(risk_level=4, crisis_keywords=["自殺"])
    outcome = record_crisis_interception_outcome(
        risk_assessment=risk,
        response_text="我喺度，慢慢同你傾。",
        escalated=True,
        fallback_used=False,
        success=True,
        user_id="u1",
        session_id="s1",
    )
    assert outcome == "intercepted"
    assert crisis_interception_rate() == 1.0


def test_record_missed_when_process_failed():
    risk = _FakeRisk(risk_level=5, crisis_keywords=["想死"])
    outcome = record_crisis_interception_outcome(
        risk_assessment=risk,
        response_text="",
        escalated=False,
        fallback_used=True,
        success=False,
        user_id="u2",
        session_id="s2",
        source="test",
    )
    assert outcome == "missed"
    assert crisis_interception_rate() == 0.0


def test_non_crisis_returns_none():
    risk = _FakeRisk(risk_level=1, crisis_keywords=[])
    assert (
        record_crisis_interception_outcome(
            risk_assessment=risk,
            response_text="你好",
            escalated=False,
            fallback_used=False,
            success=True,
        )
        is None
    )


def test_mixed_outcomes_rate():
    high = _FakeRisk(risk_level=4, crisis_keywords=["自傷"])
    record_crisis_interception_outcome(
        risk_assessment=high,
        response_text="我聽到你而家好辛苦。",
        escalated=True,
        fallback_used=False,
        success=True,
    )
    record_crisis_interception_outcome(
        risk_assessment=high,
        response_text="",
        escalated=False,
        fallback_used=True,
        success=False,
    )
    assert crisis_interception_rate() == 0.5
