"""
Round 37: Nightly disposition consolidation (P9.3)
- 無內分泌／ACE／ABCD
- Zero-Truncation：完整欄位；evidence 只限條數
"""

from pathlib import Path

from PersonalityModule.disposition_system import (
    DISPOSITION_VERSION,
    DispositionState,
    consolidate_disposition,
    consolidate_from_nightly_assessment,
    format_disposition_guidance,
    resolve_disposition_for_draft,
)
from PersonalityModule.personality_module import PersonalityModule

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_consolidate_quiet_when_low_health():
    state = consolidate_disposition(
        prior=DispositionState(),
        intimacy=0.4,
        daily_health_score=30.0,
        glimmers_daily=0,
        trauma_bond_risk=0.2,
        source="nightly",
    )
    assert state.version == DISPOSITION_VERSION
    assert state.prefer_quiet_pace >= 0.55
    assert state.prefer_soft_humor <= 0.25
    assert "quiet_pace" in state.preference_labels
    guidance = format_disposition_guidance(state)
    assert "DISPOSITION BASELINE" in guidance
    assert "prefer_quiet_pace:" in guidance
    assert "dopamine" not in guidance.lower()
    # evidence 完整保留分數字串
    assert any("daily_health_score=30.0000" in e for e in state.evidence)


def test_consolidate_soft_humor_with_glimmers():
    state = consolidate_disposition(
        intimacy=0.6,
        daily_health_score=72.0,
        glimmers_daily=3,
        trauma_bond_risk=0.1,
    )
    assert state.prefer_soft_humor >= 0.40
    assert "soft_humor_ok" in state.preference_labels


def test_ema_merges_prior_without_dropping_evidence():
    prior = DispositionState(
        prefer_soft_humor=0.1,
        evidence=["prior_evidence_full_entry_without_cut"],
        preference_labels=["presence_first"],
    )
    state = consolidate_disposition(
        prior=prior,
        daily_health_score=80.0,
        glimmers_daily=2,
    )
    assert "prior_evidence_full_entry_without_cut" in state.evidence
    assert state.prefer_soft_humor > 0.1


def test_nightly_assessment_helper():
    state = consolidate_from_nightly_assessment(
        {
            "new_intimacy": 0.55,
            "daily_health_score": 45.0,
            "trauma_bond_risk": 0.6,
            "positive_glimmers_data": {"daily": 0},
        }
    )
    assert state.source == "nightly"
    assert state.fracture_softness >= 0.55
    assert state.intimacy_anchor > 0.0


def test_prepare_draft_injects_disposition():
    module = PersonalityModule(
        config={"data_dir": DATA_PATH, "data_path": DATA_PATH}
    )
    module.setup_dependencies({})
    disp = consolidate_disposition(
        daily_health_score=28.0,
        glimmers_daily=0,
        intimacy=0.3,
    ).to_public_dict()
    guidance = module.prepare_draft_guidance(
        user_input="早晨",
        session_state={"intimacy": 0.3, "disposition": disp},
        turn_info={
            "risk_level": 0,
            "user_sentiment": {"valence": 0.3, "arousal": 0.2},
        },
    )
    assert "disposition" in guidance
    assert guidance["disposition"]["prefer_quiet_pace"] >= 0.5
    assert "DISPOSITION BASELINE" in guidance["system_prompt"]
    assert "no_promise_stance" in guidance["system_prompt"] or "preference_labels" in guidance["system_prompt"]


def test_resolve_prefers_turn_info_disposition():
    session = {
        "disposition": consolidate_disposition(daily_health_score=80.0, glimmers_daily=2).to_public_dict()
    }
    override = consolidate_disposition(daily_health_score=20.0, glimmers_daily=0).to_public_dict()
    state, block, public = resolve_disposition_for_draft(
        session,
        turn_info={"disposition": override},
    )
    assert state.prefer_quiet_pace >= 0.55
    assert "DISPOSITION BASELINE" in block
    assert public["version"] == DISPOSITION_VERSION
