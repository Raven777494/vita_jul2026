from PersonalityModule.gsw_engine import GSWEngine
from PersonalityModule.personality_module import PersonalityModule


def test_echo_generation_blocked_by_critical_alert_even_with_low_signal():
    engine = GSWEngine(config={})
    should_generate, score = engine.judge_eternal_echo_generation(
        response="我好感動，終於明白要珍惜。",
        extracted_info={
            "user_sentiment": {"intensity": 0.9},
            "narrative_drift_signal": 0.1,
            "narrative_drift_alert_level": "critical",
        },
        session_state={},
    )

    assert should_generate is False
    assert score == 0.0


def test_echo_generation_blocked_by_warning_alert_floor():
    engine = GSWEngine(config={})
    should_generate, score = engine.judge_eternal_echo_generation(
        response="我好感動，終於明白要珍惜。",
        extracted_info={
            "user_sentiment": {"intensity": 0.9},
            "narrative_drift_signal": 0.2,
            "narrative_drift_alert_level": "warning",
        },
        session_state={},
    )

    assert should_generate is False
    assert 0.0 <= score < 0.75


def test_apply_meta_drift_alert_prefers_higher_priority_level():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    merged = module._apply_meta_drift_alert(
        drift_info={"alert_level": "critical", "drift_score": 0.9},
        meta_control={"drift_alert_level": "warning"},
    )

    assert merged["alert_level"] == "critical"
    assert merged["metacognitive_drift_alert_level"] == "warning"
