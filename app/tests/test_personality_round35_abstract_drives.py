"""
Round 35: Abstract drives connection_hunger / curiosity_drive
- 無內分泌／ACE
- Zero-Truncation：完整 public dict + guidance 塊
- 危機壓制議程
"""

from pathlib import Path

from PersonalityModule.drive_system import (
    DRIVE_VERSION,
    DriveState,
    apply_interaction_satiation,
    format_drive_guidance,
    metabolize_drives,
    resolve_drives_for_draft,
)
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.system_prompt_builder import SystemPromptBuilder

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_metabolize_grows_with_idle_hours():
    prior = DriveState(
        connection_hunger=0.3,
        curiosity_drive=0.2,
        last_interaction_ts=1_000_000.0,
    )
    state = metabolize_drives(
        prior=prior,
        now_ts=1_000_000.0 + 24 * 3600,
        intensity="medium",
        risk_level=0,
    )
    assert state.connection_hunger > 0.3
    assert state.curiosity_drive > 0.2
    assert state.hours_since_contact == 24.0


def test_crisis_suppresses_agenda():
    prior = DriveState(
        connection_hunger=0.9,
        curiosity_drive=0.9,
        last_interaction_ts=1_000_000.0,
    )
    state = metabolize_drives(
        prior=prior,
        now_ts=1_000_000.0 + 72 * 3600,
        intensity="crisis",
        risk_level=4,
    )
    assert state.crisis_suppressed is True
    assert state.active_agenda == []
    assert state.connection_hunger <= 0.15
    guidance = format_drive_guidance(state)
    assert "ABSTRACT DRIVES" in guidance
    assert "crisis_suppressed: true" in guidance
    assert "Do not initiate check-in" in guidance
    assert "dopamine" not in guidance.lower()
    assert "cortisol" not in guidance.lower()


def test_satiation_lowers_hunger_and_sets_timestamp():
    prior = DriveState(connection_hunger=0.8, curiosity_drive=0.7)
    after = apply_interaction_satiation(
        state=prior,
        user_input="今日發生咗啲新嘢想同你分享",
        intimacy_delta=0.02,
        intensity="medium",
        now_ts=2_000_000.0,
    )
    assert after.connection_hunger < 0.8
    assert after.curiosity_drive < 0.7
    assert after.last_interaction_ts == 2_000_000.0
    assert after.active_agenda == []
    public = after.to_public_dict()
    assert public["version"] == DRIVE_VERSION
    assert "satiation_this_turn" in public
    assert "connection" in public["satiation_this_turn"]


def test_prepare_draft_guidance_exposes_drives_zt():
    module = PersonalityModule(
        config={"data_dir": DATA_PATH, "data_path": DATA_PATH}
    )
    module.setup_dependencies({})
    session = {
        "intimacy": 0.3,
        "drive_state": {
            "connection_hunger": 0.8,
            "curiosity_drive": 0.7,
            "last_interaction_ts": 1.0,
            "version": DRIVE_VERSION,
        },
    }
    guidance = module.prepare_draft_guidance(
        user_input="今日天氣幾好",
        session_state=session,
        turn_info={
            "risk_level": 0,
            "user_sentiment": {"valence": 0.4, "arousal": 0.3},
        },
    )
    assert "drive_state" in guidance
    ds = guidance["drive_state"]
    assert isinstance(ds, dict)
    assert "connection_hunger" in ds
    assert "curiosity_drive" in ds
    assert "active_agenda" in ds
    assert "ABSTRACT DRIVES" in guidance["system_prompt"]
    assert (
        "NO PROMISES" in guidance["system_prompt"]
        or "Do not make promises" in guidance["system_prompt"]
    )


def test_system_prompt_builder_includes_drive_block():
    builder = SystemPromptBuilder(config={"data_path": DATA_PATH})
    _, block, public = resolve_drives_for_draft(
        {
            "drive_state": {
                "connection_hunger": 0.9,
                "curiosity_drive": 0.8,
                "last_interaction_ts": 1.0,
            }
        },
        intensity="low",
        risk_level=0,
        now_ts=1.0 + 100 * 3600,
    )
    prompt = builder.build_system_prompt(
        primary_island="Friend",
        user_input="傾下計",
        context={
            "intimacy": 0.4,
            "intensity": "low",
            "drive_guidance": block,
            "drive_state": public,
        },
    )
    assert "ABSTRACT DRIVES" in prompt
    assert "connection_hunger:" in prompt
    assert "curiosity_drive:" in prompt
