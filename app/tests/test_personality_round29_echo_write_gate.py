"""
Round 29 / P7 — Echo 寫入閘（Consolidation 衛生）
- EchoWriteGate 統一 deny_reason／trace
- hint／critical／crisis 自傳／正史 id／canon source 拒寫
- MemoryChain／PersonalityModule skip API 對齊
- Zero-Truncation：trace 記錄完整字元數，不截斷正文
- Bugfix：VAD valence/arousal 可驅動 judge 情感分
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PersonalityModule.echo_write_gate import (
    ECHO_WRITE_GATE_VERSION,
    DENY_CANON_SOURCE,
    DENY_CRITICAL_DRIFT,
    DENY_CRISIS_AUTOBIOGRAPHY,
    DENY_IMMUTABLE_ID,
    DENY_ORCHESTRATOR_HINT,
    EchoWriteGate,
    sentiment_affect_intensity,
)
from PersonalityModule.gsw_engine import GSWEngine
from PersonalityModule.memory_manager import MemoryManager
from PersonalityModule.personality_module import PersonalityModule
from app.services.memory_chain_service import MemoryChainService

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def _module() -> PersonalityModule:
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )
    module.setup_dependencies({})
    return module


def test_p7_gate_wired_on_setup():
    module = _module()
    assert module.echo_write_gate is not None
    assert isinstance(module.echo_write_gate, EchoWriteGate)
    assert module.echo_write_gate.version == ECHO_WRITE_GATE_VERSION


def test_p7_turn_policy_hint_and_critical():
    gate = EchoWriteGate()
    d1 = gate.evaluate_turn_policy(
        final_response="我喺度陪住你。",
        user_input="今日好攰",
        turn_info={"orchestrator_hints": {"skip_echo_consolidation": True}},
        session_state={},
    )
    assert d1.allowed is False
    assert d1.deny_reason == DENY_ORCHESTRATOR_HINT

    d2 = gate.evaluate_turn_policy(
        final_response="我喺度。",
        user_input="你好",
        drift_info={"alert_level": "critical"},
        session_state={},
    )
    assert d2.allowed is False
    assert d2.deny_reason == DENY_CRITICAL_DRIFT


def test_p7_crisis_autobiography_blocked():
    gate = EchoWriteGate()
    long_response = "我細個時屋企好靜。" + ("陪住你。" * 30)
    d = gate.evaluate_turn_policy(
        final_response=long_response,
        user_input="講下以前",
        turn_info={"intensity": "crisis"},
        session_state={},
    )
    assert d.allowed is False
    assert d.deny_reason == DENY_CRISIS_AUTOBIOGRAPHY
    # Zero-Truncation：字元數完整
    assert d.response_chars == len(long_response)


def test_p7_pre_store_rejects_canon_source_and_immutable_id():
    gate = EchoWriteGate()
    d1 = gate.evaluate_pre_store(
        user_input="hi",
        response="我會陪住你。",
        echo_id="echo_ok",
        echo_score=0.8,
        metadata={"source": "seele_childhood_canon", "canon_mutable": False},
    )
    assert d1.allowed is False
    assert d1.deny_reason == DENY_CANON_SOURCE

    d2 = gate.evaluate_pre_store(
        user_input="hi",
        response="我會陪住你。",
        echo_id="memory_01",
        echo_score=0.8,
        metadata={"source": "eternal_echo", "canon_mutable": False},
    )
    assert d2.allowed is False
    assert d2.deny_reason == DENY_IMMUTABLE_ID

    d3 = gate.evaluate_pre_store(
        user_input="hi",
        response="我會陪住你。",
        echo_id="echo_ok",
        echo_score=0.8,
        metadata={"source": "eternal_echo", "canon_mutable": True},
    )
    assert d3.allowed is False
    assert d3.deny_reason == DENY_CANON_SOURCE


def test_p7_should_skip_api_compatible():
    module = _module()
    skip, reason = module._should_skip_echo_consolidation(
        turn_info={"orchestrator_hints": {"skip_echo_consolidation": True}},
        session_state={},
        final_response="我喺度。",
        drift_info={"alert_level": "none"},
        user_input="你好",
    )
    assert skip is True
    assert reason == DENY_ORCHESTRATOR_HINT
    assert isinstance(module.echo_write_gate, EchoWriteGate)


def test_p7_sentiment_affect_from_vad():
    # Bug fix：無 intensity 時仍可由 arousal/valence 計算
    assert sentiment_affect_intensity({"arousal": 0.9, "valence": -0.2}) > 0.6
    assert sentiment_affect_intensity({"intensity": 0.2}) == 0.2


def test_p7_gsw_judge_uses_vad_affect():
    engine = GSWEngine(config={}, memory_manager=MemoryManager())
    # 含觸發詞 + 高 arousal → 應可達閾值（無 intensity 鍵）
    ok, score = engine.judge_eternal_echo_generation(
        response="我明白你，會好好珍惜同陪伴。",
        extracted_info={
            "user_sentiment": {"valence": 0.3, "arousal": 0.85, "vad_scale": "signed"},
            "narrative_drift_signal": 0.0,
            "narrative_drift_alert_level": "none",
        },
        session_state={"intimacy": 0.3},
    )
    assert isinstance(score, float)
    assert score > 0.0
    assert ok is True


def test_p7_gsw_generate_blocked_by_hint():
    engine = GSWEngine(config={}, memory_manager=MemoryManager())

    async def _run():
        return await engine.generate_and_store_echo(
            user_input="今日好攰",
            response="我明白你，會好好珍惜同陪伴。",
            extracted_info={
                "skip_echo_consolidation": True,
                "user_sentiment": {"arousal": 0.9, "valence": 0.2},
            },
            session_state={"user_id": "u1", "session_id": "s1"},
            echo_score=0.9,
        )

    echo_id = asyncio.run(_run())
    assert echo_id == ""


def test_p7_memory_chain_risk_gate():
    engine = GSWEngine(config={}, memory_manager=MemoryManager())
    service = MemoryChainService(gsw_engine=engine)

    async def _run():
        return await service.persist_turn(
            user_id="u1",
            session_id="s1",
            user_input="我好驚",
            response="我喺度陪住你。",
            user_embedding=[0.1, 0.2],
            risk_level=4,
            force=False,
        )

    assert asyncio.run(_run()) is None


def test_p7_background_consolidation_records_trace():
    module = _module()
    mm = MemoryManager()
    module.gsw_engine = GSWEngine(config={}, memory_manager=mm)
    session = {"intimacy": 0.2, "user_id": "u1", "session_id": "s1"}
    turn = {
        "orchestrator_hints": {"skip_echo_consolidation": True},
        "user_sentiment": {"arousal": 0.8, "valence": 0.1},
    }

    async def _run():
        await module._background_consolidation(
            user_input="今日好攰",
            final_response="我明白你，會珍惜同陪伴。" * 5,
            perception_data={"primary_island": "Empath"},
            session_state=session,
            turn_info=turn,
            heretic_log={},
            system_prompt="x",
            drift_info={"alert_level": "none"},
        )

    asyncio.run(_run())
    assert session.get("echo_write_allowed") is False
    assert session.get("echo_write_deny_reason") == DENY_ORCHESTRATOR_HINT
    trace = session.get("echo_write_trace") or {}
    assert trace.get("deny_reason") == DENY_ORCHESTRATOR_HINT
    assert trace.get("version") == ECHO_WRITE_GATE_VERSION
    assert int(trace.get("response_chars") or 0) == len("我明白你，會珍惜同陪伴。" * 5)
