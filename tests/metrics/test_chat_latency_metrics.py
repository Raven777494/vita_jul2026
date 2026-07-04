"""Tests for chat processing latency histogram (P4-3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.metrics.chat_latency_metrics import (
    record_chat_processing_seconds,
    resolve_processing_path,
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
