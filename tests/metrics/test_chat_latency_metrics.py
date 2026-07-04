"""Tests for chat processing latency histogram (P4-3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.metrics.chat_latency_metrics import (
    CHAT_PROCESSING_SECONDS,
    record_chat_processing_from_risk_level,
    record_chat_processing_seconds,
    resolve_processing_path,
    resolve_processing_path_from_risk_level,
)
from app.metrics.crisis_metrics import CrisisSignalSnapshot, is_crisis_signal


@dataclass
class _FakeRisk:
    risk_level: int
    crisis_keywords: List[str]
    suicidal_indicators: int = 0
    self_harm_indicators: int = 0


def test_resolve_processing_path_crisis_by_risk_level():
    assert resolve_processing_path(_FakeRisk(risk_level=3, crisis_keywords=[])) == "crisis"


def test_resolve_processing_path_normal_low_risk():
    assert resolve_processing_path(_FakeRisk(risk_level=1, crisis_keywords=[])) == "normal"


def test_resolve_processing_path_crisis_by_keyword():
    assert resolve_processing_path(_FakeRisk(risk_level=1, crisis_keywords=["想死"])) == "crisis"


def test_resolve_processing_path_none_is_normal():
    assert resolve_processing_path(None) == "normal"


def test_record_chat_processing_seconds_accepts_crisis_and_normal():
    record_chat_processing_seconds(path="crisis", duration_seconds=1.5)
    record_chat_processing_seconds(path="normal", duration_seconds=0.2)
    record_chat_processing_seconds(path="invalid", duration_seconds=0.1)


def test_crisis_signal_alignment_with_histogram_path():
    risk = _FakeRisk(risk_level=4, crisis_keywords=["自殺"])
    snapshot = CrisisSignalSnapshot(
        risk_level=risk.risk_level,
        crisis_keywords=tuple(risk.crisis_keywords),
    )
    assert is_crisis_signal(snapshot)
    assert resolve_processing_path(risk) == "crisis"


def test_resolve_processing_path_from_risk_level_crisis():
    assert resolve_processing_path_from_risk_level(3) == "crisis"
    assert resolve_processing_path_from_risk_level(5) == "crisis"


def test_resolve_processing_path_from_risk_level_normal():
    assert resolve_processing_path_from_risk_level(0) == "normal"
    assert resolve_processing_path_from_risk_level(1) == "normal"


def test_record_chat_processing_from_risk_level_observes_histogram():
    labels = CHAT_PROCESSING_SECONDS.labels(path="normal")
    before = labels._sum.get()
    record_chat_processing_from_risk_level(risk_level=1, duration_seconds=0.4)
    assert labels._sum.get() >= before + 0.4
