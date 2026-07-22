from PersonalityModule.metacognitive_system import MetacognitiveSystem


def test_monitor_process_records_decision_with_correlation_id(tmp_path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 5}, data_dir=str(tmp_path))
    cid = "dec_150_monitor"

    control = meta.monitor_process(
        user_input="我今晚有啲唔穩定。",
        island_activation={"Mother": 0.3, "Friend": 0.2, "Empath": 0.3, "Self": 0.2},
        extracted_info={
            "decision_correlation_id": cid,
            "user_sentiment": {"intensity": 0.4},
        },
        session_state={"intimacy": 0.3, "turn_history": []},
    )

    assert control["decision_correlation_id"] == cid
    decision_logs = meta.knowledge_base.get("strategy_decision_log", [])
    assert decision_logs
    assert decision_logs[-1]["decision_correlation_id"] == cid


def test_evaluate_outcome_records_correlation_id(tmp_path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 5}, data_dir=str(tmp_path))
    cid = "dec_150_eval"

    _ = meta.monitor_process(
        user_input="今日有啲累。",
        island_activation={"Mother": 0.2, "Friend": 0.2, "Empath": 0.3, "Self": 0.3},
        extracted_info={"decision_correlation_id": cid, "user_sentiment": {"intensity": 0.2}},
        session_state={"intimacy": 0.2, "turn_history": []},
    )
    meta.evaluate_outcome(
        final_response="我會陪住你。",
        feedback_metrics={
            "decision_correlation_id": cid,
            "intimacy_delta": 0.01,
            "sentiment_delta": 0.2,
            "is_safe": True,
        },
    )

    eval_logs = meta.knowledge_base.get("strategy_evaluation_log", [])
    assert eval_logs
    assert eval_logs[-1]["decision_correlation_id"] == cid
    assert eval_logs[-1]["is_success"] is True
