"""
Round 16: P0 contract regressions
- MemoryChainService respects should_store=False
- Orchestrator unpacks PersonalityModule.anchor() -> (str, dict)
- MemoryManager GSW fallback store/search exists
"""

import asyncio
from typing import Any, Dict, Optional, Tuple

from app.services.memory_chain_service import MemoryChainService
from PersonalityModule.memory_manager import MemoryManager


class _FakeGSW:
    def __init__(self, should_store: bool = False, echo_score: float = 0.1):
        self.should_store = should_store
        self.echo_score = echo_score
        self.store_calls = 0

    def judge_eternal_echo_generation(self, response, extracted_info, session_state):
        return self.should_store, self.echo_score

    async def generate_and_store_echo(self, **kwargs):
        self.store_calls += 1
        return "echo_test_1"


def test_memory_chain_skips_persist_when_should_store_false():
    gsw = _FakeGSW(should_store=False, echo_score=0.1)
    service = MemoryChainService(gsw_engine=gsw)

    echo_id = asyncio.run(
        service.persist_turn(
            user_id="u1",
            session_id="s1",
            user_input="今日好攰",
            response="我喺度陪住你。",
            user_embedding=[0.1, 0.2, 0.3],
            response_embedding=[0.2, 0.1, 0.0],
            force=False,
        )
    )

    assert echo_id is None
    assert gsw.store_calls == 0


def test_memory_chain_persists_when_should_store_true():
    gsw = _FakeGSW(should_store=True, echo_score=0.8)
    service = MemoryChainService(gsw_engine=gsw)

    echo_id = asyncio.run(
        service.persist_turn(
            user_id="u1",
            session_id="s1",
            user_input="終於決定改變",
            response="我聽到你講珍惜同陪伴。",
            user_embedding=[0.1, 0.2, 0.3],
            response_embedding=[0.2, 0.1, 0.0],
        )
    )

    assert echo_id == "echo_test_1"
    assert gsw.store_calls == 1


def test_memory_chain_judge_exception_defaults_to_skip():
    class BrokenGSW(_FakeGSW):
        def judge_eternal_echo_generation(self, response, extracted_info, session_state):
            raise RuntimeError("judge failed")

    gsw = BrokenGSW()
    service = MemoryChainService(gsw_engine=gsw)

    echo_id = asyncio.run(
        service.persist_turn(
            user_id="u1",
            session_id="s1",
            user_input="hello",
            response="world",
            user_embedding=[0.1],
        )
    )

    assert echo_id is None
    assert gsw.store_calls == 0


def _unpack_anchor_result(anchor_result: Any) -> Tuple[str, Optional[Dict]]:
    """Mirror orchestrator contract unpacking for PersonalityModule.anchor()."""
    response_text = ""
    state_out = None
    if isinstance(anchor_result, tuple) and len(anchor_result) >= 2:
        response_text = anchor_result[0] if isinstance(anchor_result[0], str) else ""
        if isinstance(anchor_result[1], dict):
            state_out = anchor_result[1]
    elif isinstance(anchor_result, dict):
        response_text = (
            anchor_result.get("response")
            or anchor_result.get("text")
            or anchor_result.get("final_response")
            or ""
        )
        if isinstance(anchor_result.get("session_state"), dict):
            state_out = anchor_result["session_state"]
    elif isinstance(anchor_result, str):
        response_text = anchor_result
    return response_text, state_out


def test_anchor_tuple_contract_is_unpacked():
    state = {"intimacy": 0.4, "turn_count": 3}
    text, out_state = _unpack_anchor_result(("我會喺度陪你。", state))

    assert text == "我會喺度陪你。"
    assert out_state is state
    assert out_state["intimacy"] == 0.4


def test_anchor_dict_and_str_contracts_still_supported():
    text, state = _unpack_anchor_result({"response": "ok", "session_state": {"a": 1}})
    assert text == "ok"
    assert state == {"a": 1}

    text2, state2 = _unpack_anchor_result("plain")
    assert text2 == "plain"
    assert state2 is None


def test_memory_manager_gsw_fallback_store_and_search():
    mm = MemoryManager()
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [0.9, 0.1, 0.0]
    vec_c = [0.0, 1.0, 0.0]

    assert mm.store({"id": "m1", "content": "a", "embedding": vec_a}) is True
    assert mm.store({"id": "m2", "content": "b", "embedding": vec_b}) is True
    assert mm.store({"id": "m3", "content": "c", "embedding": vec_c}) is True

    hits = mm.search(vec_a, k=2)
    assert len(hits) == 2
    assert hits[0]["id"] == "m1"
    assert "similarity" in hits[0]
