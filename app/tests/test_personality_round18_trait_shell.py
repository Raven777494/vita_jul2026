"""
Round 18 (updated): PersonaGraph shell labels + safety tone
（已拆除 trait_volumes / expression_budget 音量分數）
"""

from pathlib import Path

from PersonalityModule.persona_graph import GRAPH_VERSION, PersonaGraph
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_persona_graph_outputs_shell_labels_not_volume_dials():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="今日想傾下計，有啲輕鬆事",
        intimacy=0.45,
        user_sentiment={"valence": 0.65, "arousal": 0.35},
        risk_level=0,
    )

    assert resolution.graph_version == GRAPH_VERSION
    assert isinstance(resolution.trait_labels, list)
    assert "溫暖" in resolution.trait_labels
    assert resolution.trait_volumes == {}
    assert resolution.expression_budget == {}
    assert "shell labels" in resolution.prompt_fragment
    assert "Trait volumes" not in resolution.prompt_fragment
    assert "Expression budget" not in resolution.prompt_fragment
    public = resolution.to_public_dict()
    assert "trait_labels" in public


def test_crisis_gate_uses_safety_sentence_not_humor_scores():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我好絕望，真係想死",
        intimacy=0.2,
        user_sentiment={"valence": 0.1, "arousal": 0.95},
        risk_level=4,
    )

    assert resolution.intensity == "crisis"
    assert "expression_gate_crisis" in resolution.active_policies
    assert "no_playful_teasing" in resolution.active_policies
    assert "hold_space_then_repair" in resolution.active_policies
    assert "no teasing" in resolution.prompt_fragment.lower()
    assert resolution.expression_budget == {}
    assert resolution.trait_volumes == {}


def test_high_gate_blocks_play_via_policy():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我好難過，成日崩潰，好無助",
        intimacy=0.3,
        user_sentiment={"valence": 0.2, "arousal": 0.8},
        risk_level=2,
    )

    assert resolution.intensity == "high"
    assert "expression_gate_high" in resolution.active_policies
    assert "no_playful_teasing" in resolution.active_policies
    assert "HIGH-TENSION SAFETY" in resolution.prompt_fragment


def test_system_prompt_writes_labels_and_crisis_safety():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我好絕望，真係想死",
        intimacy=0.15,
        user_sentiment={"valence": 0.05, "arousal": 0.95},
        risk_level=4,
    )

    prompt = builder.build_system_prompt(
        primary_island=resolution.primary_island,
        user_input="我好絕望，真係想死",
        context={
            "intimacy": 0.15,
            "intensity": resolution.intensity,
            "persona_resolution": resolution.to_public_dict(),
            "trait_labels": resolution.trait_labels,
        },
    )

    assert "TRAIT / EXPRESSION CONTROL:" in prompt
    assert "Trait shell labels:" in prompt
    assert "SAFETY TONE (crisis):" in prompt
    assert "No teasing" in prompt
    assert "warmth)=" not in prompt
    assert "play)=" not in prompt


def test_system_prompt_prefers_persona_graph_intensity_over_local_detect():
    """修 bug：避免 builder 本地偵測與 PersonaGraph intensity 不一致。"""
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    prompt = builder.build_system_prompt(
        primary_island="Empath",
        user_input="今日天氣不錯",
        context={
            "intimacy": 0.2,
            "intensity": "crisis",
            "trait_labels": ["溫暖", "謙虛"],
        },
    )
    assert "SAFETY TONE (crisis):" in prompt
    assert "TONE (normal / low-risk chat):" not in prompt


def test_prepare_draft_guidance_exposes_labels_not_budgets():
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
        }
    )
    module.setup_dependencies({})

    guidance = module.prepare_draft_guidance(
        user_input="我好攰，想有人陪",
        session_state={"intimacy": 0.15, "turn_count": 2},
        turn_info={
            "user_sentiment": {
                "valence": 0.3,
                "arousal": 0.6,
                "polarity": "negative",
                "intensity": 0.6,
            },
            "risk_level": 1,
        },
    )

    assert isinstance(guidance.get("trait_labels"), list)
    assert guidance["trait_volumes"] == {}
    assert guidance["expression_budget"] == {}
    assert "TRAIT / EXPRESSION CONTROL:" in guidance["system_prompt"]
    assert guidance["graph_version"] == GRAPH_VERSION
    # 未講童年／過去 → 不注入正史
    assert not guidance.get("soul_memory")
    assert "SOUL MEMORY" not in guidance["system_prompt"]
