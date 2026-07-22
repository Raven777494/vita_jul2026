from PersonalityModule.eternal_echo_memory import EternalEchoMemory


def _seed_memory(memory: EternalEchoMemory) -> str:
    echo_id = memory.generate_and_store(
        user_input="今日想傾下心事。",
        response="我聽住你講，我哋一步一步嚟。",
        extracted_info={"response_embedding": [0.2, 0.1], "user_sentiment": {"arousal": 0.2, "valence": 0.1}},
        session_state={"turn_count": 1, "intimacy": 0.3},
        echo_score=0.7,
    )
    assert echo_id != ""
    return echo_id


def test_policy_trace_for_recall_operations(tmp_path):
    memory = EternalEchoMemory(data_dir=str(tmp_path))
    _seed_memory(memory)

    _ = memory.recall_by_island("Unknown", k=3, policy_level="strict")
    _ = memory.recall_by_intimacy_range(0.0, 1.0, k=2, policy_level="critical")

    logs = memory.get_policy_audit_trail(limit=10)
    ops = [entry["operation"] for entry in logs]
    assert "recall_by_island" in ops
    assert "recall_by_intimacy_range" in ops

    island_log = next(entry for entry in logs if entry["operation"] == "recall_by_island")
    assert island_log["policy_level"] == "strict"

    range_log = next(entry for entry in logs if entry["operation"] == "recall_by_intimacy_range")
    assert range_log["policy_level"] == "critical"


def test_policy_trace_for_delete_echo(tmp_path):
    memory = EternalEchoMemory(data_dir=str(tmp_path))
    echo_id = _seed_memory(memory)

    ok = memory.delete_echo(echo_id, policy_level="critical")
    assert ok is True

    logs = memory.get_policy_audit_trail(limit=10)
    delete_logs = [entry for entry in logs if entry["operation"] == "delete_echo"]
    assert delete_logs
    latest = delete_logs[-1]
    assert latest["policy_level"] == "critical"
    assert latest["details"]["echo_id"] == echo_id
    assert latest["details"]["result"] == "archived"
