import json
from pathlib import Path

from PersonalityModule.eternal_echo_memory import EternalEchoMemory
from PersonalityModule.metacognitive_system import MetacognitiveSystem


def test_metacognitive_sets_critical_drift_guardrails(tmp_path: Path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 6}, data_dir=str(tmp_path))
    control = meta.monitor_process(
        user_input="你係咪我命中注定嘅另一半？",
        island_activation={"Mother": 0.6, "Friend": 0.2, "Empath": 0.1, "Self": 0.1},
        extracted_info={
            "user_sentiment": {"intensity": 0.5},
            "narrative_drift_signal": 0.9,
            "retrieved_memories": [
                {"id": "echo_abc", "content": "我爸爸以前住喺另一個城市。"}
            ],
        },
        session_state={"intimacy": 0.2, "turn_history": []},
    )

    assert control["drift_alert_level"] == "critical"
    assert control["force_reflection"] is True
    assert control["restrict_memory"] is True
    assert control["gsw_top_k"] == 2
    assert control["narrative_guardrails"]["enabled"] is True


def test_metacognitive_keeps_flow_when_no_drift(tmp_path: Path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 5}, data_dir=str(tmp_path))
    control = meta.monitor_process(
        user_input="我今日有啲累，但想慢慢處理。",
        island_activation={"Mother": 0.2, "Friend": 0.2, "Empath": 0.3, "Self": 0.3},
        extracted_info={"user_sentiment": {"intensity": 0.2}},
        session_state={"intimacy": 0.4, "turn_history": []},
    )

    assert control["drift_alert_level"] == "none"
    assert control["narrative_guardrails"]["enabled"] is False


def test_eternal_echo_blocks_critical_narrative_drift(tmp_path: Path):
    # 準備 canonical，故意不讓回應命中 canonical 字串，觸發 critical 阻擋
    canon = {
        "memories": [
            {"title": "舊唐樓風扇與午睡", "anchor": "舊唐樓", "lesson": "被照顧能長出穩定依附感"}
        ]
    }
    (tmp_path / "seele_childhood_canon.json").write_text(
        json.dumps(canon, ensure_ascii=False), encoding="utf-8"
    )

    memory = EternalEchoMemory(data_dir=str(tmp_path))
    echo_id = memory.generate_and_store(
        user_input="你仲記唔記得以前？",
        response="我爸爸以前長期住喺外地，所以我成日一個人。",
        extracted_info={"response_embedding": [1.0, 0.0], "narrative_drift_signal": 0.8},
        session_state={"turn_count": 1, "intimacy": 0.3},
        echo_score=0.8,
    )

    assert echo_id == ""
    assert len(memory.memories) == 0


def test_eternal_echo_warning_memory_is_stored_but_filtered_in_recall(tmp_path: Path):
    memory = EternalEchoMemory(data_dir=str(tmp_path))
    risky_id = memory.generate_and_store(
        user_input="你會唔會一直同我一齊？",
        response="我覺得你係我命中注定，我會同你一直走落去。",
        extracted_info={
            "response_embedding": [1.0, 0.0],
            "user_sentiment": {"arousal": 0.2, "valence": 0.1},
            "narrative_drift_signal": 0.5,
        },
        session_state={"turn_count": 1, "intimacy": 0.2},
        echo_score=0.75,
    )
    safe_id = memory.generate_and_store(
        user_input="今日壓力好大。",
        response="我聽住你講，我哋一步一步處理。",
        extracted_info={
            "response_embedding": [1.0, 0.0],
            "user_sentiment": {"arousal": 0.2, "valence": 0.1},
        },
        session_state={"turn_count": 2, "intimacy": 0.2},
        echo_score=0.7,
    )

    assert risky_id != ""
    assert safe_id != ""

    recalled = memory.recall_top_k([1.0, 0.0], k=5, min_similarity=0.0)
    recalled_ids = [item["memory"]["id"] for item in recalled]

    assert risky_id not in recalled_ids
    assert safe_id in recalled_ids

    health = memory.health_check()
    assert any("Narrative drift risky memories too high" in issue for issue in health["issues"])
