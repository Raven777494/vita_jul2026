import pytest
from pathlib import Path

from PersonalityModule.config import PersonalityConfig
from PersonalityModule.island_fusion import IslandFusion
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_intimacy_stage_mapping_matches_requested_ladder():
    cfg = PersonalityConfig()

    assert cfg.get_intimacy_level_name(0.0) == "普通人"
    assert cfg.get_intimacy_level_name(0.25) == "普通朋友"
    assert cfg.get_intimacy_level_name(0.45) == "好友"
    assert cfg.get_intimacy_level_name(0.65) == "關切"
    assert cfg.get_intimacy_level_name(0.8) == "關心"
    assert cfg.get_intimacy_level_name(0.95) == "蜜友"


def test_system_prompt_respects_stage_and_avoids_forced_intimacy():
    builder = SystemPromptBuilder(
        config={
            "data_path": DATA_PATH,
        }
    )

    prompt = builder.build_system_prompt(
        primary_island="Empath",
        user_input="我今日有啲唔舒服",
        context={"intimacy": 0.1},
    )

    assert "CURRENT RELATIONSHIP STAGE: 普通人" in prompt
    assert "closest and most trusted friend" not in prompt
    assert "do not skip stages" in prompt


@pytest.mark.parametrize(
    ("intimacy", "must_contain", "must_not_contain"),
    [
        (0.1, "我記得", "寶貝"),
        (0.5, "你知道嗎", "寶貝"),
    ],
)
def test_memory_weaving_does_not_over_intimate_early(intimacy, must_contain, must_not_contain):
    fusion = IslandFusion(data_dir=DATA_PATH)
    text = fusion.format_memory_by_mood("那次你很難過", "Empath", intimacy)

    assert must_contain in text
    assert must_not_contain not in text
