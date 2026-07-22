"""
Round 20: 過去／童年觸發 → 雙庫檢索最多 1 段正史
"""

from pathlib import Path

from PersonalityModule.personality_module import PersonalityModule

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")
VOCAL_PATH = (
    Path(__file__).resolve().parents[2]
    / "PersonalityModule"
    / "vocal_personality_layer.py"
)


def _module() -> PersonalityModule:
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )
    module.setup_dependencies({})
    return module


def test_no_soul_memory_without_past_topic():
    module = _module()
    selected = module._select_soul_memory(
        "我而家好攰，想有人陪",
        primary_island="Empath",
        intensity="medium",
    )
    assert selected is None


def test_past_topic_selects_one_from_dual_library():
    module = _module()
    selected = module._select_soul_memory(
        "講起我童年同以前屋企，有時會諗起風扇聲",
        primary_island="Mother",
        intensity="medium",
    )
    assert selected is not None
    assert selected.get("source") in {"seele_childhood_canon", "core_memories"}
    assert str(selected.get("content") or "").strip()
    guidance = module._format_soul_memory_guidance(selected)
    assert "SOUL MEMORY" in guidance
    assert "memory_id:" in guidance
    # Zero-Truncation：完整 content
    assert str(selected["content"]) in guidance


def test_prepare_draft_injects_soul_memory_only_on_past_topic():
    module = _module()

    no_past = module.prepare_draft_guidance(
        user_input="今日天氣幾好",
        session_state={"intimacy": 0.2, "turn_count": 1},
        turn_info={"user_sentiment": {"valence": 0.7, "arousal": 0.3}, "risk_level": 0},
    )
    assert not no_past.get("soul_memory")
    assert "SOUL MEMORY" not in no_past["system_prompt"]

    with_past = module.prepare_draft_guidance(
        user_input="我想講下童年以前嘅事，細個時屋企點樣",
        session_state={"intimacy": 0.2, "turn_count": 2},
        turn_info={"user_sentiment": {"valence": 0.5, "arousal": 0.4}, "risk_level": 0},
    )
    assert with_past.get("soul_memory")
    assert with_past.get("soul_memory_id")
    assert "SOUL MEMORY" in with_past["system_prompt"]
    # 最多一段：guidance 區塊只應出現一次標題
    assert with_past["system_prompt"].count("SOUL MEMORY") == 1


def test_vocal_source_has_zero_truncation_no_hard_cut():
    source = VOCAL_PATH.read_text(encoding="utf-8")
    assert "draft_response[:2000]" not in source
    assert "keeping full text (no truncation)" in source
