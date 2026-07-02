"""Orchestrator companion gate tests (P3-3 / ADR-001)."""

from __future__ import annotations

import logging

import pytest

from app.clinical.companion_language_policy import validate_user_facing_text
from app.clinical.user_facing_gate import apply_user_facing_gate
from app.orchestrator import Orchestrator


def test_gate_sanitizes_forbidden_hotline_text() -> None:
    unsafe = "請立即撥打23892222撒瑪利亞熱線，去急診住院。"
    gate = apply_user_facing_gate(unsafe, risk_level=4, source="test")
    assert gate.sanitized is True
    ok, issues = validate_user_facing_text(gate.text)
    assert ok, issues


def test_gate_passes_clean_companion_text() -> None:
    safe = "我喺度聽你講，呢刻我們慢慢呼吸，好嗎？"
    gate = apply_user_facing_gate(safe, risk_level=2, source="test")
    assert gate.sanitized is False
    assert gate.text == safe


def test_orchestrator_get_safe_reply_always_passes_policy() -> None:
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("test.orchestrator.gate")
    for tier in ("critical", "high_risk", "medium_risk", "system_error", "fallback"):
        text = orch._get_safe_reply(tier)
        ok, issues = validate_user_facing_text(text)
        assert ok, f"tier={tier} issues={issues}"


def test_orchestrator_finalize_sanitizes_llm_like_output() -> None:
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("test.orchestrator.finalize")
    result = {
        "success": True,
        "risk_level": 4,
        "metadata": {},
        "warnings": [],
    }
    unsafe = "你應該即刻去急診，請致電熱線23892222。"
    final = orch._finalize_turn_outcome(
        result,
        unsafe,
        session_id="gate-test-session",
        fallback_reason=None,
    )
    ok, issues = validate_user_facing_text(final)
    assert ok, issues
    assert result["metadata"].get("companion_gate_sanitized") is True


def test_orchestrator_finalize_preserves_valid_long_response() -> None:
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("test.orchestrator.finalize.ok")
    result = {
        "success": True,
        "risk_level": 1,
        "metadata": {},
        "warnings": [],
    }
    safe = (
        "我聽到你今日過得好辛苦，呢種感受係真實嘅。"
        "我哋唔使一次過解決所有嘢，今晚只要陪住你慢慢呼吸已經好足夠。"
    )
    final = orch._finalize_turn_outcome(
        result,
        safe,
        session_id="gate-test-session-2",
        fallback_reason=None,
    )
    assert final == safe
    assert result["metadata"].get("companion_gate_sanitized") is not True
