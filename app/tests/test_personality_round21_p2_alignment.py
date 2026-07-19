"""
Round 21: P2 工程對齊 + 實測缺口補內容
- canon 補 memory_15/16/17
- 雙庫 weight／island／trigger 對齊
- fallback 唔再被 core weight=5 碾壓
"""

from pathlib import Path

from PersonalityModule.personality_module import PersonalityModule

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")
CANON_PATH = Path(DATA_PATH) / "seele_childhood_canon.json"


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


def test_canon_has_gap_fill_memories_15_to_17():
    import json

    payload = json.loads(CANON_PATH.read_text(encoding="utf-8"))
    ids = {m.get("id") for m in payload.get("memories", []) if isinstance(m, dict)}
    assert {"memory_01", "memory_14", "memory_15", "memory_16", "memory_17"} <= ids
    # Zero-Truncation：既有 memory_01 內容仍完整
    m01 = next(m for m in payload["memories"] if m["id"] == "memory_01")
    assert "天花扇慢慢轉" in m01["content"]


def test_normalize_soul_weight_aligns_orb_scale():
    module = _module()
    assert module._normalize_soul_weight(0.85) == 0.85
    assert abs(module._normalize_soul_weight(5.0) - 1.0) < 1e-9
    assert module._normalize_soul_weight(2.5) == 0.5


def test_canon_candidates_get_derived_affinity_and_keywords():
    module = _module()
    cands = module._iter_soul_memory_candidates()
    m01 = next(c for c in cands if c.get("memory_id") == "memory_01")
    assert m01["source"] == "seele_childhood_canon"
    assert isinstance(m01.get("island_affinity"), dict)
    assert m01["island_affinity"].get("Mother", 0) > 0
    assert isinstance(m01.get("trigger_keywords"), list)
    assert m01["trigger_keywords"]


def test_fallback_prefers_canon_over_heavy_core_weight():
    """修 bug：過去話題無關鍵詞時，唔應因 orb weight=5 永遠落 core。"""
    module = _module()
    selected = module._select_soul_memory(
        "我想講下以前嘅事",
        primary_island="Empath",
        intensity="medium",
    )
    assert selected is not None
    assert selected.get("source") == "seele_childhood_canon"


def test_gap_memory_15_space_after_anger():
    module = _module()
    selected = module._select_soul_memory(
        "以前發脾氣嗰陣好想靜一靜，唔想即刻傾",
        primary_island="Empath",
        intensity="high",
    )
    assert selected is not None
    assert selected.get("memory_id") == "memory_15"
    guidance = module._format_soul_memory_guidance(selected)
    assert "你想靜一陣我都喺度" in guidance
    assert str(selected.get("content") or "") in guidance


def test_gap_memory_16_exam_no_toxic_positivity():
    module = _module()
    selected = module._select_soul_memory(
        "講起以前考試成績差，好唔想聽人叫睇開啲",
        primary_island="Mother",
        intensity="high",
    )
    assert selected is not None
    assert selected.get("memory_id") == "memory_16"


def test_gap_memory_17_remember_small_thing():
    module = _module()
    selected = module._select_soul_memory(
        "以前同朋友傾偈，有人記得我講過嘅小事",
        primary_island="Friend",
        intensity="low",
    )
    assert selected is not None
    assert selected.get("memory_id") == "memory_17"


def test_core_exam_orb_has_narrative_fields():
    module = _module()
    cands = module._iter_soul_memory_candidates()
    exam = next(c for c in cands if c.get("memory_id") == "gold_hk_01")
    assert exam.get("source") == "core_memories"
    assert exam.get("lesson")
    assert exam.get("companion_line")
    # 原文未截斷
    assert "爸爸溫柔開解我" in exam.get("content", "")
