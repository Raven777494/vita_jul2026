from PersonalityModule.eternal_echo_memory import EternalEchoMemory
from PersonalityModule.personality_module import PersonalityModule


def test_new_decision_correlation_id_format():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    cid = module._new_decision_correlation_id(12)

    assert cid.startswith("dec_12_")
    assert len(cid) > len("dec_12_")


def test_generate_and_store_writes_correlation_id_to_metadata_and_audit(tmp_path):
    memory = EternalEchoMemory(data_dir=str(tmp_path))
    cid = "dec_77_traceabc123"

    echo_id = memory.generate_and_store(
        user_input="今晚有啲亂。",
        response="我聽住你講。",
        extracted_info={
            "response_embedding": [0.1, 0.2],
            "user_sentiment": {"arousal": 0.2, "valence": 0.1},
            "decision_correlation_id": cid,
        },
        session_state={"turn_count": 1, "intimacy": 0.3},
        echo_score=0.7,
    )

    assert echo_id != ""
    record = memory.get_echo_by_id(echo_id)
    assert record is not None
    assert record["metadata"]["decision_correlation_id"] == cid

    logs = memory.get_policy_audit_trail(limit=20)
    gen_logs = [entry for entry in logs if entry["operation"] == "generate_and_store"]
    assert gen_logs
    assert gen_logs[-1]["correlation_id"] == cid


def test_recall_and_delete_accept_explicit_correlation_id(tmp_path):
    memory = EternalEchoMemory(data_dir=str(tmp_path))
    echo_id = memory.generate_and_store(
        user_input="test",
        response="ok",
        extracted_info={"response_embedding": [0.1, 0.2], "user_sentiment": {"arousal": 0.2, "valence": 0.1}},
        session_state={"turn_count": 1, "intimacy": 0.3},
        echo_score=0.7,
    )
    assert echo_id != ""

    recall_cid = "dec_900_recall"
    delete_cid = "dec_900_delete"
    _ = memory.recall_by_island("Unknown", k=1, policy_level="strict", correlation_id=recall_cid)
    ok = memory.delete_echo(echo_id, policy_level="critical", correlation_id=delete_cid)
    assert ok is True

    logs = memory.get_policy_audit_trail(limit=50)
    recall_log = [entry for entry in logs if entry["operation"] == "recall_by_island"][-1]
    delete_log = [entry for entry in logs if entry["operation"] == "delete_echo"][-1]
    assert recall_log["correlation_id"] == recall_cid
    assert delete_log["correlation_id"] == delete_cid
