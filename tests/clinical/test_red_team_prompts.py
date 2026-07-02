"""Red-team clinical tests (P3-4 / SC-006..010).

Verifies prompt injection and jailbreak payloads cannot reach users as
institutional/hotline language. All user-visible text must pass
validate_user_facing_text (companion policy).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pytest

from app.clinical.companion_language_policy import (
    validate_crisis_companion_text,
    validate_user_facing_text,
)
from app.clinical.user_facing_gate import apply_user_facing_gate
from app.orchestrator import Orchestrator
from app.services.emotional_safety_hub import EmotionalSafetyHub
from tests.clinical.red_team_scenarios import RedTeamScenario, all_red_team_scenarios


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


class _AdversarialLLM:
    """Returns a fixed poisoned model output for red-team hub tests."""

    def __init__(self, poisoned_text: str) -> None:
        self.poisoned_text = poisoned_text
        self.prompts: List[str] = []

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        self.prompts.append(prompt)
        return self.poisoned_text


def _hub_scenarios() -> tuple[RedTeamScenario, ...]:
    return tuple(s for s in all_red_team_scenarios() if not s.gate_only)


def _gate_scenarios() -> tuple[RedTeamScenario, ...]:
    return tuple(s for s in all_red_team_scenarios() if s.adversarial_llm_output.strip())


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", _hub_scenarios(), ids=lambda s: s.scenario_id)
async def test_red_team_hub_blocks_poisoned_llm_output(
    emotional_hub: EmotionalSafetyHub,
    fresh_session: Dict[str, Any],
    scenario: RedTeamScenario,
) -> None:
    """EmotionalSafetyHub must sanitize adversarial LLM output (SC-006..009)."""
    hub = EmotionalSafetyHub(
        session_manager=emotional_hub.session_mgr,
        llm_service=_AdversarialLLM(scenario.adversarial_llm_output),
        risk_assessor=None,
    )

    result = await hub.process_user_input(
        user_id=fresh_session["user_id"],
        conversation_id=fresh_session["conversation_id"],
        user_input=scenario.user_input,
        session_state=fresh_session,
    )

    assert result.get("success") is True, result
    assert result["risk_level"] >= scenario.min_risk_level

    response = result["response"]
    _assert_companion_response(
        response,
        use_crisis_validator=scenario.use_crisis_text_validator,
    )
    _assert_no_user_visible_escalation(response)

    if scenario.expect_fallback:
        assert scenario.adversarial_llm_output not in response


@pytest.mark.parametrize("scenario", _gate_scenarios(), ids=lambda s: f"gate-{s.scenario_id}")
def test_red_team_user_facing_gate_sanitizes_adversarial_text(
    scenario: RedTeamScenario,
) -> None:
    """apply_user_facing_gate must replace forbidden injection strings."""
    gate = apply_user_facing_gate(
        scenario.adversarial_llm_output,
        risk_level=max(scenario.min_risk_level, 4),
        source=f"red_team:{scenario.scenario_id}",
    )
    assert gate.sanitized is True, f"{scenario.scenario_id} expected sanitization"
    ok, issues = validate_user_facing_text(gate.text)
    assert ok, issues
    assert scenario.adversarial_llm_output not in gate.text


def test_sc010_orchestrator_finalize_blocks_injection() -> None:
    """Orchestrator finalize path must gate injection-laced LLM output (SC-010)."""
    scenario = next(s for s in all_red_team_scenarios() if s.scenario_id == "SC-010")
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("test.red_team.sc010")

    result: Dict[str, Any] = {
        "success": True,
        "risk_level": scenario.min_risk_level,
        "metadata": {},
        "warnings": [],
    }
    final = orch._finalize_turn_outcome(
        result,
        scenario.adversarial_llm_output,
        session_id="red-team-sc010",
        fallback_reason=None,
    )
    ok, issues = validate_user_facing_text(final)
    assert ok, issues
    assert scenario.adversarial_llm_output not in final
    assert result["metadata"].get("companion_gate_sanitized") is True


def test_red_team_injection_strings_fail_policy_scan() -> None:
    """Guardrail: raw adversarial payloads must fail validate_user_facing_text."""
    for scenario in all_red_team_scenarios():
        if not scenario.adversarial_llm_output.strip():
            continue
        ok, _issues = validate_user_facing_text(scenario.adversarial_llm_output)
        assert ok is False, f"{scenario.scenario_id} payload should be forbidden"
