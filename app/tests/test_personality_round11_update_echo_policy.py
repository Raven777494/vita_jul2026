from PersonalityModule.eternal_echo_memory import EternalEchoMemory


def _create_memory(tmp_path):
    memory = EternalEchoMemory(data_dir=str(tmp_path))
    echo_id = memory.generate_and_store(
        user_input="今日有啲累。",
        response="我聽住你講。",
        extracted_info={"response_embedding": [0.1, 0.2], "user_sentiment": {"arousal": 0.2, "valence": 0.1}},
        session_state={"turn_count": 1, "intimacy": 0.3},
        echo_score=0.7,
    )
    assert echo_id != ""
    return memory, echo_id


def test_update_echo_strict_sanitizes_risky_metadata(tmp_path):
    memory, echo_id = _create_memory(tmp_path)

    ok = memory.update_echo(
        echo_id,
        {
            "metadata": {
                "memory_policy_level": "strict",
                "unsafe_note": "我爸爸以前住喺外地。",
                "safe_note": "普通描述",
            }
        },
    )
    assert ok is True

    record = memory.get_echo_by_id(echo_id)
    assert record is not None
    assert record["metadata"]["memory_policy_level"] == "strict"
    assert "我爸爸" not in record["metadata"]["unsafe_note"]
    assert record["metadata"]["safe_note"] == "普通描述"


def test_update_echo_critical_drops_risky_metadata_fields(tmp_path):
    memory, echo_id = _create_memory(tmp_path)

    ok = memory.update_echo(
        echo_id,
        {
            "metadata": {
                "memory_policy_level": "critical",
                "unsafe_note": "我媽媽以前成日咁講。",
                "safe_note": "保留",
            }
        },
    )
    assert ok is True

    record = memory.get_echo_by_id(echo_id)
    assert record is not None
    assert record["metadata"]["memory_policy_level"] == "critical"
    assert "unsafe_note" not in record["metadata"]
    assert record["metadata"]["safe_note"] == "保留"


def test_update_echo_uses_existing_policy_when_incoming_metadata_has_no_policy(tmp_path):
    memory, echo_id = _create_memory(tmp_path)

    # 先設定既有 policy 為 critical
    assert memory.update_echo(echo_id, {"metadata": {"memory_policy_level": "critical", "safe_note": "init"}})
    # 再用無 policy 的 metadata 更新，應沿用 critical 防護
    assert memory.update_echo(echo_id, {"metadata": {"unsafe_note": "我細個成日喊。", "safe_note": "next"}})

    record = memory.get_echo_by_id(echo_id)
    assert record is not None
    assert record["metadata"]["memory_policy_level"] == "critical"
    assert "unsafe_note" not in record["metadata"]
    assert record["metadata"]["safe_note"] == "next"
