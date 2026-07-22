import pytest

from PersonalityModule.personality_module import PersonalityModule


@pytest.mark.asyncio
async def test_background_consolidation_applies_meta_boundary_multiplier():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data", "boundary_multiplier": 1.0})
    session_state = {"intimacy": 0.5, "turn_history": []}

    await module._background_consolidation(
        user_input="多謝你一直聽我講。",
        final_response="我喺度。",
        perception_data={"primary_island": "Empath"},
        session_state=session_state,
        turn_info={"metacognitive_control": {"boundary_multiplier": 1.0, "force_reflection": False}},
        heretic_log={},
        system_prompt="",
        drift_info={"drift_score": 0.1, "alert_level": "none"},
    )

    assert session_state["intimacy"] > 0.55
    assert session_state["last_intimacy_delta"] > 0.05
    assert session_state["turn_history"][-1]["meta_force_reflection"] is False


@pytest.mark.asyncio
async def test_background_consolidation_force_reflection_caps_intimacy_growth():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data", "boundary_multiplier": 1.0})
    session_state = {"intimacy": 0.5, "turn_history": []}

    await module._background_consolidation(
        user_input="謝謝你，我真係感動。",
        final_response="我聽住你。",
        perception_data={"primary_island": "Empath"},
        session_state=session_state,
        turn_info={"metacognitive_control": {"boundary_multiplier": 0.5, "force_reflection": True, "drift_alert_level": "warning"}},
        heretic_log={},
        system_prompt="",
        drift_info={"drift_score": 0.7, "alert_level": "warning"},
    )

    assert 0.0 < session_state["last_intimacy_delta"] <= 0.01
    assert session_state["turn_history"][-1]["meta_force_reflection"] is True
    assert session_state["turn_history"][-1]["meta_boundary_multiplier"] == 0.5


@pytest.mark.asyncio
async def test_background_consolidation_critical_alert_hard_limits_intimacy_delta():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data", "boundary_multiplier": 1.0})
    session_state = {"intimacy": 0.5, "turn_history": []}

    await module._background_consolidation(
        user_input="謝謝你。",
        final_response="我明白。",
        perception_data={"primary_island": "Empath"},
        session_state=session_state,
        turn_info={"metacognitive_control": {"boundary_multiplier": 1.0, "force_reflection": True, "drift_alert_level": "critical"}},
        heretic_log={},
        system_prompt="",
        drift_info={"drift_score": 0.9, "alert_level": "critical"},
    )

    assert session_state["last_intimacy_delta"] <= 0.0025
    assert session_state["turn_history"][-1]["drift_alert_level"] == "critical"
