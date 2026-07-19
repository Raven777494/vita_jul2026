import pytest

from PersonalityModule.gsw_engine import GSWEngine
from PersonalityModule.heretic_coordinator import HereticCoordinator


@pytest.mark.asyncio
async def test_gsw_detect_drift_returns_correlation_id():
    engine = GSWEngine(config={})

    async def _fake_search_memories(query_vector, k=5, min_similarity=0.0, user_id=None):
        return [{"id": "core_001", "similarity": 0.8}]

    engine.search_memories = _fake_search_memories  # type: ignore[method-assign]
    cid = "dec_100_testcorr"
    result = await engine.detect_drift(
        response_vector=[0.1, 0.2],
        user_input="test",
        session_state={},
        restrict_memory=False,
        candidate_k=5,
        correlation_id=cid,
    )

    assert result["available"] is True
    assert result["correlation_id"] == cid


@pytest.mark.asyncio
async def test_heretic_log_contains_decision_correlation_id():
    coordinator = HereticCoordinator(config={})
    cid = "dec_200_heretic"

    response, log = await coordinator.coordinate(
        draft_response="我會陪你。",
        user_input="我好亂。",
        island_activation={"Empath": 1.0},
        primary_island="Empath",
        drift_info={"drift_score": 0.2, "decision_correlation_id": cid},
        sensitivity_result={},
        extracted_info={},
        session_state={"intimacy": 0.3},
    )

    assert isinstance(response, str)
    assert log["decision_correlation_id"] == cid
