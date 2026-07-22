from PersonalityModule.gsw_engine import GSWEngine


def test_echo_generation_allowed_when_no_drift_and_high_signal():
    engine = GSWEngine(config={})
    should_generate, score = engine.judge_eternal_echo_generation(
        response="我好感動，終於明白要珍惜身邊人。",
        extracted_info={
            "user_sentiment": {"intensity": 0.9},
            "narrative_drift_signal": 0.0,
        },
        session_state={},
    )

    assert should_generate is True
    assert score >= 0.6


def test_echo_generation_penalized_under_medium_drift():
    engine = GSWEngine(config={})
    should_generate, score = engine.judge_eternal_echo_generation(
        response="我好感動，終於明白要珍惜身邊人。",
        extracted_info={
            "user_sentiment": {"intensity": 0.9},
            "narrative_drift_signal": 0.7,
        },
        session_state={},
    )

    assert should_generate is False
    assert 0.0 <= score < 0.75


def test_echo_generation_blocked_under_critical_drift():
    engine = GSWEngine(config={})
    should_generate, score = engine.judge_eternal_echo_generation(
        response="我好感動，終於明白要珍惜身邊人。",
        extracted_info={
            "user_sentiment": {"intensity": 0.9},
            "narrative_drift_signal": 0.9,
        },
        session_state={},
    )

    assert should_generate is False
    assert score == 0.0
