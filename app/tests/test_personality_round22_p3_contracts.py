"""
Round 22: P3 管線契約
- P3.1 pre-draft prompt 重用
- P3.2 anchor -> (str, dict)；response embedding 契約說明
- P3.3 orchestrator_hints 白名單（無 ABCD）
- P3.4 echo 不可寫正史 id；可 skip consolidation
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PersonalityModule.config import PersonalityConfig
from PersonalityModule.memory_manager import MemoryManager
from PersonalityModule.personality_module import (
    ORCHESTRATOR_HINT_WHITELIST,
    PersonalityModule,
)

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


def _unpack_anchor_result(anchor_result: Any) -> Tuple[str, Optional[Dict]]:
    """Mirror orchestrator contract unpacking."""
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


def test_apply_context_hooks_whitelist_only_no_abcd():
    hooks = PersonalityModule.apply_context_hooks(
        turn_info={
            "orchestrator_hints": {
                "user_mode_hint": "A",
                "skip_echo_consolidation": True,
                "abcd_class": "should_ignore",
                "user_tier": "VIP",
            },
            "expression_preference": "quiet",
        },
        session_state={"force_quiet_presence": True},
    )
    assert set(hooks.keys()) <= set(ORCHESTRATOR_HINT_WHITELIST)
    assert hooks["user_mode_hint"] == "A"
    assert hooks["skip_echo_consolidation"] is True
    assert hooks["expression_preference"] == "quiet"
    assert hooks["force_quiet_presence"] is True
    assert "abcd_class" not in hooks
    assert "user_tier" not in hooks


def test_prepare_draft_honors_force_quiet_and_exposes_prompt_contract():
    module = _module()
    guidance = module.prepare_draft_guidance(
        user_input="今日天氣幾好",
        session_state={"intimacy": 0.2, "turn_count": 1},
        turn_info={
            "user_sentiment": {"valence": 0.7, "arousal": 0.3},
            "risk_level": 0,
            "orchestrator_hints": {"force_quiet_presence": True},
        },
    )
    assert guidance["prompt_contract"] == "pre_draft_full_no_truncation"
    assert guidance["intensity"] in {"high", "crisis"}
    assert "no_playful_teasing" in guidance["active_policies"]
    assert guidance["orchestrator_hints"].get("force_quiet_presence") is True
    # Zero-Truncation：完整 prompt
    assert len(guidance["system_prompt"]) > 100


def test_pre_draft_prompt_reuse_skips_rebuild():
    module = _module()
    pre = module.prepare_draft_guidance(
        user_input="我好攰",
        session_state={"intimacy": 0.1, "turn_count": 1},
        turn_info={"user_sentiment": {"valence": 0.3, "arousal": 0.5}, "risk_level": 0},
    )
    calls = {"build": 0}
    original = module.system_prompt_builder.build_system_prompt

    def tracked(*args, **kwargs):
        calls["build"] += 1
        return original(*args, **kwargs)

    module.system_prompt_builder.build_system_prompt = tracked

    # 模擬 anchor Phase 2a：有 pre_draft system_prompt 就不重算
    personality_system_prompt = str(pre.get("system_prompt") or "")
    prompt_reused = bool(personality_system_prompt.strip())
    if not prompt_reused:
        personality_system_prompt = module.system_prompt_builder.build_system_prompt(
            primary_island=pre["primary_island"],
            user_input="我好攰",
            context={"intimacy": 0.1},
        )

    assert prompt_reused is True
    assert calls["build"] == 0
    assert "PERSONA GRAPH STATE" in personality_system_prompt


def test_anchor_tuple_contract_unpack():
    text, state = _unpack_anchor_result(("我會陪住你。", {"intimacy": 0.2, "prompt_reused": True}))
    assert text == "我會陪住你。"
    assert state["prompt_reused"] is True

    text2, state2 = _unpack_anchor_result({"response": "ok", "session_state": {"a": 1}})
    assert text2 == "ok"
    assert state2 == {"a": 1}


def test_memory_manager_refuses_immutable_soul_ids():
    mm = MemoryManager()
    assert mm.store({"id": "memory_01", "content": "x"}) is False
    assert mm.store({"id": "core_001", "content": "x"}) is False
    assert mm.store({"id": "gold_hk_01", "content": "x"}) is False
    assert mm.store({"id": "echo_ok_1", "content": "陪住你", "response": "陪住你"}) is True
    assert any(m.get("id") == "echo_ok_1" for m in mm._store)


def test_skip_echo_consolidation_hint():
    module = _module()
    skip, reason = module._should_skip_echo_consolidation(
        turn_info={"orchestrator_hints": {"skip_echo_consolidation": True}},
        session_state={},
        final_response="我喺度。",
        drift_info={"alert_level": "none"},
    )
    assert skip is True
    assert reason == "orchestrator_hint_skip"

    skip2, reason2 = module._should_skip_echo_consolidation(
        turn_info={},
        session_state={},
        final_response="我喺度。",
        drift_info={"alert_level": "critical"},
    )
    assert skip2 is True
    assert reason2 == "critical_narrative_drift"


def test_config_refuse_canon_mutation():
    cfg = PersonalityConfig.__new__(PersonalityConfig)
    try:
        cfg.refuse_canon_file_mutation("seele_childhood_canon.json")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "immutable" in str(exc).lower()


def test_is_immutable_soul_memory_id():
    assert PersonalityModule.is_immutable_soul_memory_id("memory_15") is True
    assert PersonalityModule.is_immutable_soul_memory_id("echo_2026") is False
