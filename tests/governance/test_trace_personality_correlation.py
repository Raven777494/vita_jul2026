from __future__ import annotations

import json
from pathlib import Path

from scripts.governance.trace_personality_correlation import collect_correlation_trace


def test_collect_correlation_trace_matches_all_sources(tmp_path: Path) -> None:
    cid = "dec_500_test"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    (data_dir / "metacognitive_knowledge.json").write_text(
        json.dumps(
            {
                "strategy_decision_log": [
                    {"decision_correlation_id": cid, "timestamp": "2026-01-01T00:00:00"},
                    {"decision_correlation_id": "other", "timestamp": "2026-01-01T00:00:01"},
                ],
                "strategy_evaluation_log": [
                    {"decision_correlation_id": cid, "timestamp": "2026-01-01T00:00:02"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data_dir / "eternal_echo_memories.json").write_text(
        json.dumps(
            [
                {
                    "id": "echo_1",
                    "timestamp": "2026-01-01T00:00:03",
                    "metadata": {"decision_correlation_id": cid},
                },
                {
                    "id": "echo_2",
                    "timestamp": "2026-01-01T00:00:04",
                    "metadata": {"decision_correlation_id": "other"},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data_dir / "eternal_echo_policy_audit.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"correlation_id": cid, "operation": "generate_and_store", "timestamp": "2026-01-01T00:00:05"}, ensure_ascii=False),
                json.dumps({"correlation_id": "other", "operation": "delete_echo", "timestamp": "2026-01-01T00:00:06"}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    report = collect_correlation_trace(data_dir=data_dir, correlation_id=cid, max_items=20)
    counts = report["summary"]["counts"]
    assert counts["metacognitive_decisions"] == 1
    assert counts["metacognitive_evaluations"] == 1
    assert counts["echo_memories"] == 1
    assert counts["policy_audit"] == 1


def test_collect_correlation_trace_handles_missing_files(tmp_path: Path) -> None:
    report = collect_correlation_trace(
        data_dir=tmp_path / "missing_data",
        correlation_id="dec_none",
        max_items=10,
    )
    counts = report["summary"]["counts"]
    assert counts["metacognitive_decisions"] == 0
    assert counts["metacognitive_evaluations"] == 0
    assert counts["echo_memories"] == 0
    assert counts["policy_audit"] == 0
