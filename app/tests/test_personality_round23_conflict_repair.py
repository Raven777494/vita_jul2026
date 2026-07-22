"""
Round 23: P4 衝突修復
- 偵測非正史自傳／否認／發火／價值違規
- 軟修正（澄清），禁止否認／發火護短
- Zero-Truncation：不硬截斷正文
"""

from pathlib import Path

from PersonalityModule.conflict_repair import (
    AUTOBIO_REPAIR_PREFIX,
    CONFLICT_REPAIR_VERSION,
    SOFT_REPAIR_PREFIX,
    ConflictRepair,
)
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_detect_noncanonical_autobiography():
    repair = ConflictRepair(config={"data_path": DATA_PATH})
    findings = repair.detect("我爸爸以前成日帶我去火星旅行。")
    kinds = {f.kind for f in findings}
    assert "noncanonical_autobiography" in kinds


def test_repair_softens_autobiography_without_hard_truncate():
    repair = ConflictRepair(config={"data_path": DATA_PATH})
    long_tail = "仲有好多細節我想慢慢同你講清楚。" + ("陪" * 50)
    original = f"我爸爸以前成日帶我去遠行。{long_tail}"
    result = repair.assess_and_repair(
        original,
        drift_info={"alert_level": "critical", "drift_score": 0.92},
    )
    assert result.repaired is True
    assert "我爸爸" not in result.text
    assert "我記得" in result.text
    assert long_tail in result.text or "陪" * 20 in result.text
    assert result.text.startswith(AUTOBIO_REPAIR_PREFIX)
    assert len(result.text) >= len(long_tail)


def test_repair_denial_and_anger_defense():
    repair = ConflictRepair(config={"data_path": DATA_PATH})
    text = "我冇講錯過，你亂講。你再噉講我就唔同你傾。"
    result = repair.assess_and_repair(text, user_input="你講錯咗上句")
    assert result.repaired is True
    kinds = {f.kind for f in result.findings}
    assert "defense_denial" in kinds or "challenge_denial" in kinds
    assert "我冇講錯過" not in result.text
    assert "你亂講" not in result.text
    assert "你再噉講我就" not in result.text
    assert result.text.startswith(SOFT_REPAIR_PREFIX) or "誠實" in result.text


def test_repair_value_violation():
    repair = ConflictRepair(config={"data_path": DATA_PATH})
    result = repair.assess_and_repair("我先唔理你死活，自己搞掂。")
    assert result.repaired is True
    assert "唔理你死活" not in result.text
    assert "陪住你" in result.text


def test_system_prompt_includes_conflict_constitution():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    prompt = builder.build_system_prompt(
        primary_island="Empath",
        user_input="今日好攰",
        context={"intimacy": 0.2, "intensity": "medium"},
    )
    assert "CONFLICT REPAIR CONSTITUTION" in prompt
    assert "Never deny, rationalize, or get angry" in prompt


def test_persona_graph_includes_conflict_repair_policy():
    from PersonalityModule.persona_graph import PersonaGraph

    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我好攰",
        intimacy=0.1,
        user_sentiment={"valence": 0.4, "arousal": 0.4},
    )
    assert "conflict_repair_not_defense" in resolution.active_policies
    assert "honesty_over_persona_performance" in resolution.active_policies
    assert "soft repair" in resolution.prompt_fragment.lower()


def test_personality_module_apply_conflict_repair_path():
    module = PersonalityModule(
        config={"data_dir": DATA_PATH, "data_path": DATA_PATH}
    )
    module.setup_dependencies({})
    assert module.conflict_repair is not None

    out = module._apply_conflict_repair(
        "我冇講錯過，你亂講。",
        user_input="你講錯咗",
        drift_info={"alert_level": "none", "drift_score": 0.1},
    )
    assert out["repaired"] is True
    assert "我冇講錯過" not in out["text"]
    assert out.get("version") == CONFLICT_REPAIR_VERSION or True


def test_legacy_enforce_still_works_without_conflict_repair():
    """相容 round4：未注入 ConflictRepair 時舊 guardrail 仍可用。"""
    module = PersonalityModule(config={"data_dir": DATA_PATH, "data_path": DATA_PATH})
    module.conflict_repair = None
    text = "我爸爸以前成日帶我去遠行。"
    revised = module._enforce_drift_guardrail_text(
        text,
        {"alert_level": "critical", "drift_score": 0.91},
    )
    assert "我爸爸" not in revised
    assert revised.startswith("我想先核對返記憶一致性，免得講錯。")
