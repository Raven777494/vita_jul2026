import pytest

from PersonalityModule.gsw_engine import GSWEngine
from PersonalityModule.personality_module import PersonalityModule


@pytest.mark.asyncio
async def test_detect_drift_restrict_memory_filters_candidates():
    engine = GSWEngine(config={})

    async def _fake_search_memories(query_vector, k=5, min_similarity=0.0, user_id=None):
        return [
            {"id": "x_1", "similarity": 0.95, "metadata": {"memory_type": "chat"}},
            {"id": "core_001", "similarity": 0.4},
        ]

    engine.search_memories = _fake_search_memories  # type: ignore[method-assign]

    unrestricted = await engine.detect_drift(
        response_vector=[0.1, 0.2],
        user_input="test",
        session_state={},
        restrict_memory=False,
        candidate_k=5,
    )
    restricted = await engine.detect_drift(
        response_vector=[0.1, 0.2],
        user_input="test",
        session_state={},
        restrict_memory=True,
        candidate_k=5,
    )

    assert unrestricted["available"] is True
    assert unrestricted["drift_score"] == pytest.approx(0.05, abs=1e-6)
    assert restricted["available"] is True
    assert restricted["closest_core_memory"]["id"] == "core_001"
    assert restricted["drift_score"] == pytest.approx(0.6, abs=1e-6)


class _PolicyAwareDriftEngine:
    def __init__(self):
        self.last_kwargs = {}

    async def detect_drift(self, **kwargs):
        self.last_kwargs = kwargs
        return {
            "drift_score": 0.42,
            "closest_core_memory": {"id": "memory_14"},
            "closest_distance": 0.42,
            "available": True,
        }


@pytest.mark.asyncio
async def test_monitor_drift_passes_meta_memory_policy():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    engine = _PolicyAwareDriftEngine()
    module.gsw_engine = engine

    result = await module._monitor_drift(
        draft_response="我喺度。",
        user_input="我有啲亂。",
        current_state={"intimacy": 0.3},
        turn_info={"response_embedding": [0.1, 0.2]},
        memory_policy={"restrict_memory": True, "gsw_top_k": 7},
    )

    assert engine.last_kwargs["restrict_memory"] is True
    assert engine.last_kwargs["candidate_k"] == 7
    assert result["restrict_memory"] is True
    assert result["candidate_k"] == 7
