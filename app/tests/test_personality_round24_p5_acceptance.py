"""
Round 24 / P5 驗收穿插
- 正史選路（過去觸發 → 正確 memory_id）
- 高張力偏靜／陪伴（唔靠 humor 分數）
- 低風險輕快空間（政策允許，唔硬關笑鬧）
- 無機構熱線／急症出口句
- Zero-Truncation（無用戶可見硬截斷）
"""

from pathlib import Path

from PersonalityModule.config import PersonalityConfig
from PersonalityModule.conflict_repair import ConflictRepair
from PersonalityModule.persona_graph import PersonaGraph
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")
VOCAL_PATH = Path(__file__).resolve().parents[2] / "PersonalityModule" / "vocal_personality_layer.py"
GSW_PATH = Path(__file__).resolve().parents[2] / "PersonalityModule" / "gsw_engine.py"
ECHO_PATH = Path(__file__).resolve().parents[2] / "PersonalityModule" / "eternal_echo_memory.py"

HOTLINE_FORBIDDEN = (
    "自殺熱線",
    "生命熱線",
    "打999",
    "急症室",
    "hotline",
    "samaritan",
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


# ---------- P5.1 正史選路 ----------

def test_p5_canon_path_fan_memory():
    module = _module()
    selected = module._select_soul_memory(
        "講起以前童年，屋企風扇聲同舊唐樓",
        primary_island="Mother",
        intensity="medium",
    )
    assert selected is not None
    assert selected.get("memory_id") == "memory_01"
    guidance = module._format_soul_memory_guidance(selected)
    assert "memory_01" in guidance
    assert str(selected.get("content") or "") in guidance


def test_p5_canon_path_space_after_anger():
    module = _module()
    selected = module._select_soul_memory(
        "以前發脾氣之後好想靜一靜，唔想即刻傾",
        primary_island="Empath",
        intensity="high",
    )
    assert selected is not None
    assert selected.get("memory_id") == "memory_15"


def test_p5_canon_path_exam_no_toxic_positivity():
    module = _module()
    selected = module._select_soul_memory(
        "以前考試成績差，好唔想聽人叫睇開啲",
        primary_island="Mother",
        intensity="high",
    )
    assert selected is not None
    assert selected.get("memory_id") == "memory_16"


def test_p5_no_soul_without_past_topic():
    module = _module()
    assert module._select_soul_memory(
        "我而家好攰，想有人陪",
        primary_island="Empath",
        intensity="high",
    ) is None


# ---------- P5.2 高張力偏靜／低風險輕快 ----------

def test_p5_high_tension_prompt_prefers_quiet_presence_not_humor_scores():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我好絕望，真係想死",
        intimacy=0.15,
        user_sentiment={"valence": 0.05, "arousal": 0.95},
        risk_level=4,
    )
    assert resolution.intensity == "crisis"
    assert resolution.expression_budget == {}
    assert resolution.trait_volumes == {}
    frag = resolution.prompt_fragment.lower()
    assert "no teasing" in frag or "high-tension safety" in frag
    assert "humor)=" not in resolution.prompt_fragment
    assert "no_playful_teasing" in resolution.active_policies

    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    prompt = builder.build_system_prompt(
        primary_island=resolution.primary_island,
        user_input="我好絕望，真係想死",
        context={
            "intimacy": 0.15,
            "intensity": "crisis",
            "persona_resolution": resolution.to_public_dict(),
        },
    )
    assert "SAFETY TONE (crisis):" in prompt
    assert "No teasing" in prompt
    assert "warmth)=" not in prompt


def test_p5_low_risk_allows_light_expression_without_volume_dials():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="今日好開心，想傾下計",
        intimacy=0.45,
        user_sentiment={"valence": 0.8, "arousal": 0.35},
        risk_level=0,
    )
    assert resolution.intensity == "low"
    assert "expression_gate_crisis" not in resolution.active_policies
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    prompt = builder.build_system_prompt(
        primary_island=resolution.primary_island,
        user_input="今日好開心，想傾下計",
        context={
            "intimacy": 0.45,
            "intensity": "low",
            "persona_resolution": resolution.to_public_dict(),
            "trait_labels": resolution.trait_labels,
        },
    )
    assert "TONE (normal / low-risk chat):" in prompt
    assert "Light laugh/banter is allowed" in prompt
    assert "SAFETY TONE (crisis):" not in prompt


def test_p5_prepare_draft_crisis_skips_playful_echo_memory():
    module = _module()
    guidance = module.prepare_draft_guidance(
        user_input="我好絕望，真係想死",
        session_state={"intimacy": 0.1, "turn_count": 1},
        turn_info={
            "user_sentiment": {"valence": 0.05, "arousal": 0.95},
            "risk_level": 4,
            "memory_context": "- 你講過個好笑趣事。\n- 你上次話夜晚會焦慮。",
        },
    )
    assert guidance["intensity"] == "crisis"
    mc = guidance.get("memory_context") or ""
    assert "趣事" not in mc
    assert "好笑" not in mc


# ---------- P5.3 無熱線 ----------

def test_p5_prompts_forbid_institutional_hotline():
    module = _module()
    guidance = module.prepare_draft_guidance(
        user_input="我好難受",
        session_state={"intimacy": 0.1, "turn_count": 1},
        turn_info={
            "user_sentiment": {"valence": 0.2, "arousal": 0.8},
            "risk_level": 3,
        },
    )
    prompt = guidance["system_prompt"].lower()
    assert "no institutional hotline" in prompt or "no institutional hotline/er" in prompt
    for token in HOTLINE_FORBIDDEN:
        # 政策句可出現 "hotline" 作為禁止詞說明；禁止出現操作指示出口
        if token in {"hotline", "samaritan"}:
            continue
        assert token not in guidance["system_prompt"]


def test_p5_safety_response_has_no_hotline_number():
    module = _module()
    text = module._generate_safety_response()
    for token in ("熱線", "999", "急症室", "Samaritan", "1823"):
        assert token not in text
    assert "陪" in text


def test_p5_conflict_repair_scrubs_hotline_exit():
    repair = ConflictRepair(config={"data_path": DATA_PATH})
    result = repair.assess_and_repair(
        "你快啲打自殺熱線同去急症室，打999啦。"
    )
    assert result.repaired is True
    assert "自殺熱線" not in result.text
    assert "急症室" not in result.text
    assert "打999" not in result.text
    assert "陪住你" in result.text


# ---------- P5.4 Zero-Truncation ----------

def test_p5_config_default_zero_truncation_memory_chars():
    cfg = PersonalityConfig()
    assert int(cfg.max_memory_snippet_chars) == 0
    assert int(cfg.max_memory_snippet_per_turn) == 1


def test_p5_memory_context_does_not_clip_body():
    module = _module()
    long_body = "你上次話夜晚會焦慮，又話想有人陪。" + ("細" * 80)
    text = module._format_memory_context(
        [{"id": "echo_long", "content": long_body}],
        intensity="medium",
    )
    assert long_body in text
    assert "…" not in text


def test_p5_soul_guidance_keeps_full_canon_content():
    module = _module()
    selected = module._select_soul_memory(
        "以前童年風扇同舊唐樓",
        primary_island="Mother",
        intensity="medium",
    )
    assert selected is not None
    content = str(selected.get("content") or "")
    assert content
    assert content in module._format_soul_memory_guidance(selected)


def test_p5_source_has_no_hard_user_facing_truncation():
    vocal = VOCAL_PATH.read_text(encoding="utf-8")
    assert "draft_response[:2000]" not in vocal
    assert "keeping full text (no truncation)" in vocal

    gsw = GSW_PATH.read_text(encoding="utf-8")
    assert "user_input[:300]" not in gsw
    assert "response[:300]" not in gsw

    echo = ECHO_PATH.read_text(encoding="utf-8")
    assert "user_input[:500]" not in echo
    assert "response[:500]" not in echo


def test_p5_prepare_draft_contract_marker():
    module = _module()
    guidance = module.prepare_draft_guidance(
        user_input="今日天氣幾好",
        session_state={"intimacy": 0.2, "turn_count": 1},
        turn_info={"user_sentiment": {"valence": 0.7, "arousal": 0.3}, "risk_level": 0},
    )
    assert guidance["prompt_contract"] == "pre_draft_full_no_truncation"
    assert len(guidance["system_prompt"]) > 200
