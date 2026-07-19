from PersonalityModule.gsw_engine import GSWEngine


def test_resolve_memory_policy_level_from_meta_control():
    engine = GSWEngine(config={})
    level = engine._resolve_memory_policy_level(
        extracted_info={"metacognitive_control": {"restrict_memory": True}},
        session_state={},
    )
    assert level == "strict"


def test_judge_eternal_echo_blocks_autobiography_when_policy_critical():
    engine = GSWEngine(config={})
    should_generate, score = engine.judge_eternal_echo_generation(
        response="我爸爸以前成日帶我出街。",
        extracted_info={
            "user_sentiment": {"intensity": 0.95},
            "narrative_drift_signal": 0.2,
            "narrative_drift_alert_level": "critical",
        },
        session_state={},
    )
    assert should_generate is False
    assert score == 0.0


def test_sanitize_metadata_by_policy_drops_noncanonical_fragments_in_critical():
    engine = GSWEngine(config={})
    cleaned = engine._sanitize_metadata_by_policy(
        metadata={
            "session_id": "s1",
            "unsafe_note": "我爸爸以前住喺外地。",
            "nested": {"memo": "我媽媽成日同我講。"},
            "arr": ["普通內容", "我細個成日喊。"],
        },
        policy_level="critical",
    )
    assert cleaned["session_id"] == "s1"
    assert "unsafe_note" not in cleaned
    assert "memo" not in cleaned["nested"]
    assert cleaned["arr"] == ["普通內容"]
