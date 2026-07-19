import pytest

from PersonalityModule.personality_module import PersonalityModule


class _StubSearchEngine:
    async def search_memories(self, query_vector, k=5, user_id=None):
        return [
            {"id": "core_001", "content": "core memory"},
            {"id": "x_1", "content": "non core", "metadata": {"memory_type": "chat"}},
            {"id": "echo_001", "content": "echo memory"},
            {"id": "memory_14", "content": "canonical memory"},
            {"id": "x_2", "content": "other"},
        ][:k]


@pytest.mark.asyncio
async def test_meta_gsw_top_k_controls_retrieval_depth():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    module.gsw_engine = _StubSearchEngine()

    memories = await module._apply_meta_memory_controls(
        user_embedding=[0.1, 0.2],
        user_id="u1",
        preloaded_memories=None,
        meta_control={"gsw_top_k": 2, "restrict_memory": False},
    )

    assert len(memories) == 2
    assert memories[0]["id"] == "core_001"


@pytest.mark.asyncio
async def test_meta_restrict_memory_filters_sources():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    module.gsw_engine = _StubSearchEngine()

    memories = await module._apply_meta_memory_controls(
        user_embedding=[0.1, 0.2],
        user_id="u1",
        preloaded_memories=None,
        meta_control={"gsw_top_k": 5, "restrict_memory": True},
    )

    ids = [m["id"] for m in memories]
    assert "core_001" in ids
    assert "echo_001" in ids
    assert "memory_14" in ids
    assert "x_1" not in ids
    assert "x_2" not in ids


@pytest.mark.asyncio
async def test_meta_controls_apply_to_preloaded_memories():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})
    preloaded = [
        {"id": "x_1", "content": "chat memory"},
        {"id": "echo_22", "content": "echo memory"},
        {"id": "memory_08", "content": "canonical memory"},
    ]

    memories = await module._apply_meta_memory_controls(
        user_embedding=[],
        user_id="u1",
        preloaded_memories=preloaded,
        meta_control={"gsw_top_k": 2, "restrict_memory": True},
    )

    ids = [m["id"] for m in memories]
    assert ids == ["echo_22"]
