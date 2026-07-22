"""
Round 34: SystemPromptBuilder speech discipline landing
- 禁三／允三
- 映照／失語協助／修復
- 不要做出承諾
Zero-Truncation: markers must appear in full prompt body.
"""

from pathlib import Path

from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_speech_discipline_and_core_moves_in_prompt():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    prompt = builder.build_system_prompt(
        primary_island="Empath",
        user_input="我今日有啲唔舒服",
        context={"intimacy": 0.2, "intensity": "medium"},
    )

    assert "SPEECH DISCIPLINE" in prompt
    assert "FORBIDDEN (禁三)" in prompt
    assert "ALLOWED (允三)" in prompt
    assert "NO PROMISES" in prompt
    assert "Do not make promises" in prompt
    assert "CORE RELATIONAL MOVES" in prompt
    assert "MIRROR (映照)" in prompt
    assert "SPEECHLESSNESS AID (失語協助)" in prompt
    assert "REPAIR (修復)" in prompt
    # Zero-Truncation: full blocks present, not stub markers only
    assert "Fake certainty" in prompt
    assert "Admit uncertainty" in prompt


def test_no_promise_survives_crisis_path():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    prompt = builder.build_system_prompt(
        primary_island="Mother",
        user_input="我好絕望，真係想死",
        context={"intimacy": 0.15, "intensity": "crisis"},
    )

    assert "NO PROMISES" in prompt
    assert "do not promise rescue or outcomes" in prompt
    assert "我會繼續聽住你" not in prompt
    assert "我喺度聽緊" in prompt
