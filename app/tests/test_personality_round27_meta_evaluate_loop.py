"""
Round 27 / P6.2 — 元認知 evaluate_outcome 閉環
- 主路徑每輪 monitor → 調參 → evaluate_outcome
- strategy_stats 影響下一輪 learned_bias
- VAD affect_intensity 進入 cognitive_load（不再依賴缺失的 intensity 鍵）
- Zero-Truncation：turn_history / 評估不硬截斷用戶可見正文
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PersonalityModule.metacognitive_system import MetacognitiveSystem
from PersonalityModule.personality_module import PersonalityModule

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_p62_evaluate_outcome_returns_full_record(tmp_path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 5}, data_dir=str(tmp_path))
    cid = "dec_p62_eval"
    meta.monitor_process(
        user_input="我今晚有啲唔穩定。",
        island_activation={"Mother": 0.4, "Friend": 0.1, "Empath": 0.4, "Self": 0.1},
        extracted_info={
            "decision_correlation_id": cid,
            "user_sentiment": {
                "valence": -0.4,
                "arousal": 0.7,
                "vad_scale": "signed",
                "method": "heuristic",
            },
        },
        session_state={"intimacy": 0.2, "turn_history": []},
    )
    long_reply = "我喺度陪住你。" + ("慢慢嚟。" * 40)
    evaluation = meta.evaluate_outcome(
        final_response=long_reply,
        feedback_metrics={
            "decision_correlation_id": cid,
            "intimacy_delta": 0.01,
            "sentiment_delta": 0.15,
            "is_safe": True,
            "conflict_repaired": False,
            "drift_alert_level": "none",
            "primary_island": "Empath",
        },
    )
    assert isinstance(evaluation, dict)
    assert evaluation["decision_correlation_id"] == cid
    assert evaluation["is_success"] is True
    assert evaluation["response_chars"] == len(long_reply)
    assert "final_response" not in evaluation
    logs = meta.knowledge_base.get("strategy_evaluation_log", [])
    assert logs
    assert logs[-1]["response_chars"] == len(long_reply)


def test_p62_learned_bias_tightens_after_poor_stats(tmp_path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 5}, data_dir=str(tmp_path))
    meta.knowledge_base["strategy_stats"] = {
        "intuitive": {
            "success": 1,
            "total": 5,
            "avg_sentiment_delta": -0.1,
        },
        "analytical": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
        "cautious": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
    }
    # 低熵（主導島明顯）→ intuitive，再套用學習偏置
    control = meta.monitor_process(
        user_input="今日普通傾下",
        island_activation={"Mother": 0.05, "Friend": 0.7, "Empath": 0.15, "Self": 0.1},
        extracted_info={
            "decision_correlation_id": "dec_bias",
            "user_sentiment": {
                "valence": 0.1,
                "arousal": 0.3,
                "vad_scale": "signed",
                "method": "heuristic",
            },
        },
        session_state={"intimacy": 0.3, "turn_history": []},
    )
    assert control.get("active_strategy") == "intuitive"
    assert control.get("learned_bias") == "underperforming_strategy"
    assert control.get("force_reflection") is True
    assert control.get("restrict_memory") is True
    assert float(control.get("heretic_temperature", 1.0)) <= 0.45


def test_p62_anchor_calls_evaluate_outcome_each_turn(tmp_path):
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )
    module.setup_dependencies({})
    module.metacognitive_system = MetacognitiveSystem(
        config={"gsw_top_k": 5},
        data_dir=str(tmp_path),
    )

    session = {"intimacy": 0.2, "turn_count": 0}
    turn_info = {
        "user_sentiment": {
            "valence": -0.5,
            "arousal": 0.6,
            "vad_scale": "signed",
            "dominant_emotion": "sad",
            "method": "heuristic",
        },
        "risk_level": 1,
        "skip_echo_consolidation": True,
        "orchestrator_hints": {"skip_echo_consolidation": True},
        "embedding": [],
        "response_embedding": [],
        "decision_correlation_id": "dec_p62_anchor",
    }
    reply = "我喺度，慢慢嚟，我陪住你。"

    async def _run():
        return await module.anchor(
            draft_response=reply,
            user_input="我有啲難受",
            session_state=session,
            turn_info=turn_info,
        )

    final, state = asyncio.run(_run())
    assert final
    assert "last_intimacy_delta" in state
    evaluation = state.get("metacognitive_evaluation") or {}
    assert evaluation.get("evaluated") is True
    assert evaluation.get("loop") == "monitor_then_evaluate"
    assert evaluation.get("decision_correlation_id") == "dec_p62_anchor"
    assert "response_chars" in evaluation
    logs = module.metacognitive_system.knowledge_base.get("strategy_evaluation_log", [])
    assert logs
    assert logs[-1]["decision_correlation_id"] == "dec_p62_anchor"


def test_p62_closed_loop_second_turn_sees_learned_stats(tmp_path):
    module = PersonalityModule(
        config={"data_dir": DATA_PATH, "data_path": DATA_PATH}
    )
    module.setup_dependencies({})
    module.metacognitive_system = MetacognitiveSystem(
        config={"gsw_top_k": 5},
        data_dir=str(tmp_path),
    )
    module.metacognitive_system.knowledge_base["strategy_stats"] = {
        "intuitive": {"success": 0, "total": 4, "avg_sentiment_delta": -0.2},
        "analytical": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
        "cautious": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
    }

    session = {"intimacy": 0.25, "turn_count": 1}
    turn_info = {
        "user_sentiment": {
            "valence": 0.05,
            "arousal": 0.25,
            "vad_scale": "signed",
            "method": "heuristic",
        },
        "risk_level": 0,
        "skip_echo_consolidation": True,
        "orchestrator_hints": {"skip_echo_consolidation": True},
        "embedding": [],
        "response_embedding": [],
        "decision_correlation_id": "dec_p62_loop2",
    }

    async def _run():
        return await module.anchor(
            draft_response="好呀，我喺度聽你講。",
            user_input="今日普通傾偈",
            session_state=session,
            turn_info=turn_info,
        )

    _final, state = asyncio.run(_run())
    assert (state.get("metacognitive_evaluation") or {}).get("evaluated") is True
    control2 = module.metacognitive_system.monitor_process(
        user_input="傾下日常",
        island_activation={"Mother": 0.05, "Friend": 0.7, "Empath": 0.15, "Self": 0.1},
        extracted_info={
            "decision_correlation_id": "dec_p62_loop2b",
            "user_sentiment": {
                "valence": 0.05,
                "arousal": 0.25,
                "vad_scale": "signed",
                "method": "heuristic",
            },
        },
        session_state=state,
    )
    assert control2.get("learned_bias") == "underperforming_strategy"
    assert control2.get("force_reflection") is True


def test_p62_monitor_uses_vad_intensity_not_missing_key(tmp_path):
    meta = MetacognitiveSystem(config={"gsw_top_k": 5}, data_dir=str(tmp_path))
    control = meta.monitor_process(
        user_input="x" * 20,
        island_activation={"Mother": 0.25, "Friend": 0.25, "Empath": 0.25, "Self": 0.25},
        extracted_info={
            "decision_correlation_id": "dec_vad_load",
            "user_sentiment": {
                "valence": -0.8,
                "arousal": 0.9,
                "vad_scale": "signed",
                "method": "heuristic",
            },
        },
        session_state={"intimacy": 0.2},
    )
    assert float(control.get("cognitive_load", 0.0)) > 0.3


def test_p62_background_skips_intimacy_when_main_path_flag_set():
    module = PersonalityModule(config={"data_dir": DATA_PATH, "data_path": DATA_PATH})
    module.setup_dependencies({})
    state = {
        "intimacy": 0.5,
        "intimacy_updated_this_turn": True,
        "last_intimacy_delta": 0.01,
        "turn_history": [],
    }
    before = state["intimacy"]

    async def _run():
        await module._background_consolidation(
            user_input="你好",
            final_response="我喺度",
            perception_data={"primary_island": "Friend", "island_activation": {}},
            session_state=state,
            turn_info={"metacognitive_control": {"boundary_multiplier": 1.0}},
            heretic_log={},
            system_prompt="",
            drift_info={"drift_score": 0.0, "alert_level": "none"},
        )

    asyncio.run(_run())
    assert state["intimacy"] == before
    assert state.get("intimacy_updated_this_turn") is False
