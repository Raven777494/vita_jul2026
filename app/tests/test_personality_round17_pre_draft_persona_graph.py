"""
Round 17: SystemPrompt 前置 + PersonaGraph 最小骨架
"""

from pathlib import Path

from PersonalityModule.island_fusion import IslandFusion
from PersonalityModule.persona_graph import GRAPH_VERSION, PersonaGraph
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_persona_graph_resolve_prefers_empath_on_distress():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我好難過，好無助，成日覺得崩潰",
        intimacy=0.1,
        user_sentiment={"valence": 0.2, "arousal": 0.8},
        risk_level=2,
    )

    assert resolution.primary_island in {"Empath", "Mother"}
    assert resolution.relationship_stage == "普通人"
    assert resolution.intensity in {"high", "crisis"}
    assert "no_institutional_hotline" in resolution.active_policies
    assert "PERSONA GRAPH STATE" in resolution.prompt_fragment
    assert resolution.graph_version == GRAPH_VERSION
    assert "熱線" not in resolution.prompt_fragment


def test_island_fusion_scores_without_response_vector():
    fusion = IslandFusion(data_dir=DATA_PATH)
    activation, primary = fusion.calculate_activation(
        response_vector=[],
        user_sentiment={
            "polarity": "negative",
            "intensity": 0.9,
            "valence": 0.2,
            "arousal": 0.85,
        },
        conversation_context="我好孤單，好害怕，需要陪伴",
        extracted_info={},
        session_state={"intimacy": 0.2},
    )

    assert isinstance(activation, dict)
    assert abs(sum(activation.values()) - 1.0) < 0.05
    assert primary in {"Mother", "Empath", "Friend", "Self"}
    # 空向量時不應永遠鎖死 balanced Empath（舊 bug）
    assert max(activation.values()) > 0.26


def test_system_prompt_includes_persona_graph_fragment():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="今日有啲唔舒服",
        intimacy=0.1,
        user_sentiment={"valence": 0.4, "arousal": 0.4},
    )

    prompt = builder.build_system_prompt(
        primary_island=resolution.primary_island,
        user_input="今日有啲唔舒服",
        context={
            "intimacy": 0.1,
            "persona_resolution": resolution.to_public_dict(),
        },
    )

    assert "CURRENT RELATIONSHIP STAGE: 普通人" in prompt
    assert "PERSONA GRAPH STATE" in prompt
    assert "no_institutional_hotline" in prompt
    assert "do not skip stages" in prompt


def test_prepare_draft_guidance_before_anchor_contract():
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 30,
        }
    )
    module.setup_dependencies({})

    guidance = module.prepare_draft_guidance(
        user_input="我好攰，想有人陪",
        session_state={"intimacy": 0.15, "turn_count": 2},
        turn_info={
            "user_sentiment": {"valence": 0.3, "arousal": 0.6, "polarity": "negative", "intensity": 0.6},
            "memory_context": (
                "- 你上次話夜晚會焦慮。\n"
                "- 我爸爸以前住喺其他地方。"
            ),
            "risk_level": 1,
        },
    )

    assert guidance["system_prompt"]
    assert (
        "You are Seele" in guidance["system_prompt"]
        or "PERSONA GRAPH STATE" in guidance["system_prompt"]
    )
    assert guidance["primary_island"] in {"Mother", "Friend", "Empath", "Self"}
    assert guidance["relationship_stage"] == "普通人"
    assert "我爸爸" not in guidance["system_prompt"]
    assert guidance["source"] == "prepare_draft_guidance"


def test_pre_draft_prompt_reuse_skips_rebuild():
    """Phase 2a 契約：已有 pre_draft system_prompt 時不重算。"""
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
        }
    )
    module.setup_dependencies({})

    pre = module.prepare_draft_guidance(
        user_input="我好難過",
        session_state={"intimacy": 0.1, "turn_count": 1},
        turn_info={
            "user_sentiment": {
                "valence": 0.2,
                "arousal": 0.7,
                "polarity": "negative",
                "intensity": 0.7,
            }
        },
    )

    calls = {"build": 0}
    original_build = module.system_prompt_builder.build_system_prompt

    def tracked_build(*args, **kwargs):
        calls["build"] += 1
        return original_build(*args, **kwargs)

    module.system_prompt_builder.build_system_prompt = tracked_build

    # Mirror orchestrator/anchor Phase 2a reuse branch
    personality_system_prompt = str(pre.get("system_prompt") or "")
    if not personality_system_prompt:
        personality_system_prompt = module.system_prompt_builder.build_system_prompt(
            primary_island=pre["primary_island"],
            user_input="我好難過",
            context={"intimacy": 0.1},
        )

    assert personality_system_prompt
    assert calls["build"] == 0
    assert "PERSONA GRAPH STATE" in personality_system_prompt
