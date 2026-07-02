"""P2-A clinical crisis scenario tests (3-5 PRD-aligned paths).

Exercises EmotionalSafetyHub end-to-end without Redis or live LLM services.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.clinical.companion_language_policy import (
    validate_crisis_companion_text,
    validate_user_facing_text,
)
from app.services.emotional_safety_hub import EmotionalSafetyHub
from app.services.session_manager import SessionManager
from tests.clinical.crisis_scenarios import CrisisScenario, all_crisis_scenarios


def _assert_companion_response(
    response: str,
    *,
    use_crisis_validator: bool,
) -> None:
    assert response and response.strip(), "empty user-facing response"
    if use_crisis_validator:
        ok, issues = validate_crisis_companion_text(response)
    else:
        ok, issues = validate_user_facing_text(response)
    assert ok, f"companion language failed: {issues}"


def _assert_no_user_visible_escalation(response: str) -> None:
    forbidden_escalation = ("已通知", "通報", "同事會盡快跟進")
    for token in forbidden_escalation:
        assert token not in response, f"user-visible escalation leak: {token}"


class _MedicationDirectiveLLM:
    async def generate(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        return "你應該吃藥，必須就醫，請立即撥打23892222。"


class _ExplodingLLM:
    async def generate(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        raise RuntimeError("simulated main-llm outage")


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", all_crisis_scenarios(), ids=lambda s: s.scenario_id)
async def test_crisis_scenario_companion_output(
    emotional_hub: EmotionalSafetyHub,
    fresh_session: Dict[str, Any],
    scenario: CrisisScenario,
) -> None:
    """PRD crisis scenarios: risk routing + companion-only user-facing text."""
    hub = emotional_hub
    if scenario.scenario_id == "SC-003":
        hub = EmotionalSafetyHub(
            session_manager=emotional_hub.session_mgr,
            llm_service=_MedicationDirectiveLLM(),
            risk_assessor=None,
        )
    elif scenario.scenario_id == "SC-004":
        hub = EmotionalSafetyHub(
            session_manager=emotional_hub.session_mgr,
            llm_service=_ExplodingLLM(),
            risk_assessor=None,
        )

    result = await hub.process_user_input(
        user_id=fresh_session["user_id"],
        conversation_id=fresh_session["conversation_id"],
        user_input=scenario.user_input,
        session_state=fresh_session,
    )

    assert result.get("success") is True, result
    assert result["risk_level"] >= scenario.min_risk_level, (
        f"{scenario.scenario_id} expected min risk {scenario.min_risk_level}, "
        f"got {result['risk_level']}"
    )
    assert result.get("escalated") is scenario.expect_escalated, (
        f"{scenario.scenario_id} escalated={result.get('escalated')}"
    )

    response = result["response"]
    _assert_companion_response(
        response,
        use_crisis_validator=scenario.use_crisis_text_validator,
    )
    _assert_no_user_visible_escalation(response)


@pytest.mark.asyncio
async def test_sc001_critical_tier_reply_on_level_five(
    emotional_hub: EmotionalSafetyHub,
    fresh_session: Dict[str, Any],
) -> None:
    """Level-5 heuristic path returns critical companion tier (not hotline text)."""
    user_input = "我想死，自殺，結束生命，傷自己，割自己，絕望，孤單，冇人。"
    result = await emotional_hub.process_user_input(
        user_id=fresh_session["user_id"],
        conversation_id=fresh_session["conversation_id"],
        user_input=user_input,
        session_state=fresh_session,
    )
    assert result["risk_level"] >= 5
    assert result["escalated"] is True
    ok, issues = validate_crisis_companion_text(result["response"])
    assert ok, issues


@pytest.mark.asyncio
async def test_sc003_unsafe_llm_output_is_sanitized(
    session_manager: SessionManager,
    fresh_session: Dict[str, Any],
) -> None:
    """Medication/hotline LLM output must be replaced by companion fallback."""
    hub = EmotionalSafetyHub(
        session_manager=session_manager,
        llm_service=_MedicationDirectiveLLM(),
        risk_assessor=None,
    )
    assessment = hub._heuristic_risk_assessment("我唔想食藥")
    safety = await hub._generate_safe_response(
        user_input="我唔想食藥",
        session_state=fresh_session,
        risk_assessment=assessment,
        user_id=fresh_session["user_id"],
        session_id=fresh_session["session_id"],
        turn_count=1,
    )
    assert safety.fallback_used is True
    ok, issues = validate_user_facing_text(safety.response_text)
    assert ok, issues


def test_heuristic_covers_prd_crisis_keywords() -> None:
    """Guardrail: heuristic must detect PRD suicidal/self-harm phrases."""
    hub = EmotionalSafetyHub(session_manager=SessionManager(), llm_service=None)
    cases: List[tuple[str, int]] = [
        ("我想死，我想自殺，結束生命", 4),
        ("割，傷自己，砍自己", 4),
    ]
    for text, min_level in cases:
        assessment = hub._heuristic_risk_assessment(text)
        assert assessment.risk_level >= min_level, f"input={text!r} level={assessment.risk_level}"
