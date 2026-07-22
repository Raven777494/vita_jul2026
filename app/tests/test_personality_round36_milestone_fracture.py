"""
Round 36: milestone／fracture → PersonalityModule draft 注入
Zero-Truncation：完整 title／description／tags；只限條數。
"""

from pathlib import Path

from PersonalityModule.milestone_fracture_bridge import (
    BRIDGE_VERSION,
    build_relational_context,
    format_relational_guidance,
    resolve_relational_context_for_draft,
)
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_build_selects_top_fractures_without_truncating_description():
    long_desc = "A" * 400
    bundle = build_relational_context(
        milestones=[
            {
                "milestone_id": 1,
                "milestone_type": "trust_breakthrough",
                "title": "信任提升",
                "description": long_desc,
                "severity": 2,
            },
            {
                "milestone_id": 2,
                "milestone_type": "crisis_signal",
                "title": "危機",
                "description": "short",
                "severity": 5,
            },
        ],
        fractures=[
            {
                "trigger_keyword": "孤獨",
                "context_tags": ["寂寞", "夜晚"],
                "trigger_count": 3,
                "emotion_spike_score": 0.7,
            },
            {
                "trigger_keyword": "考試",
                "context_tags": ["壓力"],
                "trigger_count": 1,
                "emotion_spike_score": 0.4,
            },
        ],
        intensity="medium",
    )
    assert bundle.version == BRIDGE_VERSION
    assert bundle.milestone_count == 2
    # severity 5 first
    assert bundle.milestones[0].milestone_type == "crisis_signal"
    # Zero-Truncation：完整 description
    assert bundle.milestones[1].description == long_desc
    assert bundle.fracture_count == 2
    assert bundle.fractures[0].trigger_keyword == "孤獨"


def test_crisis_policy_in_guidance():
    _, guidance, public = resolve_relational_context_for_draft(
        milestones=[
            {
                "milestone_type": "relationship_bond",
                "title": "關係連結",
                "description": "第一次認真傾心",
                "severity": 2,
            }
        ],
        fractures=[
            {
                "trigger_keyword": "被丟低",
                "context_tags": ["遺棄"],
                "trigger_count": 2,
                "emotion_spike_score": 0.8,
            }
        ],
        intensity="crisis",
    )
    assert "RELATIONAL CONTEXT" in guidance
    assert "第一次認真傾心" in guidance
    assert "被丟低" in guidance
    assert "quiet presence first" in guidance
    assert public["fracture_count"] == 1
    assert public["milestone_count"] == 1


def test_prepare_draft_injects_relational_context():
    module = PersonalityModule(
        config={"data_dir": DATA_PATH, "data_path": DATA_PATH}
    )
    module.setup_dependencies({})
    guidance = module.prepare_draft_guidance(
        user_input="我今日有啲唔開心",
        session_state={"intimacy": 0.4},
        turn_info={
            "risk_level": 0,
            "user_sentiment": {"valence": 0.2, "arousal": 0.5},
            "recent_milestones": [
                {
                    "milestone_id": 9,
                    "milestone_type": "turn_milestone_10",
                    "title": "第十回合",
                    "description": "我哋傾咗十次",
                    "severity": 1,
                }
            ],
            "triggered_fractures": [
                {
                    "trigger_keyword": "唔開心",
                    "context_tags": ["情緒低落"],
                    "trigger_count": 4,
                    "emotion_spike_score": 0.6,
                    "comfort_efficiency": 0.55,
                }
            ],
        },
    )
    assert "relational_context" in guidance
    assert guidance["relational_context"]["milestone_count"] == 1
    assert guidance["relational_context"]["fracture_count"] == 1
    prompt = guidance["system_prompt"]
    assert "RELATIONAL CONTEXT" in prompt
    assert "第十回合" in prompt
    assert "我哋傾咗十次" in prompt
    assert "唔開心" in prompt
    assert "情緒低落" in prompt


def test_system_prompt_builder_writes_relational_block():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    _, block, public = resolve_relational_context_for_draft(
        milestones=[
            {
                "milestone_type": "hope_restored",
                "title": "希望回升",
                "description": "見到曙光",
                "severity": 2,
            }
        ],
        fractures=[],
        intensity="low",
    )
    prompt = builder.build_system_prompt(
        primary_island="Friend",
        user_input="傾下計",
        context={
            "intimacy": 0.5,
            "intensity": "low",
            "relational_guidance": block,
            "relational_context": public,
        },
    )
    assert "RELATIONAL CONTEXT" in prompt
    assert "希望回升" in prompt
    assert "見到曙光" in prompt
