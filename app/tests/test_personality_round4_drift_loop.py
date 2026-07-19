import pytest

from PersonalityModule.heretic_coordinator import HereticCoordinator
from PersonalityModule.personality_module import PersonalityModule


class _StubDriftEngine:
    async def detect_drift(self, response_vector, user_input, session_state):
        return {
            "drift_score": 0.9,
            "closest_core_memory": {"id": "memory_14"},
            "closest_distance": 0.9,
            "available": True,
        }


@pytest.mark.asyncio
async def test_monitor_drift_classifies_critical_and_returns_context():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data", "drift_threshold": 0.65})
    module.gsw_engine = _StubDriftEngine()

    result = await module._monitor_drift(
        draft_response="我會陪住你。",
        user_input="我有啲亂。",
        current_state={"intimacy": 0.3},
        turn_info={"response_embedding": [0.1, 0.2]},
    )

    assert result["available"] is True
    assert result["alert_level"] == "critical"
    assert result["drift_score"] == 0.9
    assert result["closest_core_memory"]["id"] == "memory_14"


def test_enforce_drift_guardrail_text_rewrites_autobiography_claims():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    text = "我爸爸以前成日帶我去遠行。"
    revised = module._enforce_drift_guardrail_text(
        text,
        {"alert_level": "critical", "drift_score": 0.91},
    )

    assert "我爸爸" not in revised
    assert revised.startswith("我想先核對返記憶一致性，免得講錯。")


def test_heretic_layer2_uses_external_drift_and_applies_guardrail():
    coordinator = HereticCoordinator(config={})
    response, corrections = coordinator._layer2_personality_check(
        response="我爸爸以前住喺外地。",
        island_activation={"Mother": 1.0},
        primary_island="Mother",
        drift_info={"drift_score": 0.92},
        intimacy=0.2,
    )

    assert any(c["type"] == "narrative_consistency_guardrail" for c in corrections)
    assert "我爸爸" not in response
    assert response.startswith("我想先核對返記憶一致性，免得講錯。")
