#!/usr/bin/env python3
"""Query end-to-end personality traces by correlation id.

Data sources:
  - PersonalityModule/data/metacognitive_knowledge.json
  - PersonalityModule/data/eternal_echo_memories.json
  - PersonalityModule/data/eternal_echo_policy_audit.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "PersonalityModule" / "data"


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _filter_by_correlation(rows: list[dict[str, Any]], correlation_id: str, key: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get(key, "")) == correlation_id]


def collect_correlation_trace(
    *,
    data_dir: Path,
    correlation_id: str,
    max_items: int = 50,
) -> dict[str, Any]:
    meta_path = data_dir / "metacognitive_knowledge.json"
    echo_path = data_dir / "eternal_echo_memories.json"
    audit_path = data_dir / "eternal_echo_policy_audit.jsonl"

    metacognitive = _load_json(meta_path, {})
    echoes = _load_json(echo_path, [])
    audits = _load_jsonl(audit_path)

    decision_log = metacognitive.get("strategy_decision_log", [])
    if not isinstance(decision_log, list):
        decision_log = []
    eval_log = metacognitive.get("strategy_evaluation_log", [])
    if not isinstance(eval_log, list):
        eval_log = []
    if not isinstance(echoes, list):
        echoes = []

    meta_decisions = _filter_by_correlation(decision_log, correlation_id, "decision_correlation_id")[-max_items:]
    meta_evaluations = _filter_by_correlation(eval_log, correlation_id, "decision_correlation_id")[-max_items:]
    policy_audits = _filter_by_correlation(audits, correlation_id, "correlation_id")[-max_items:]

    matched_echoes: list[dict[str, Any]] = []
    for item in echoes:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("decision_correlation_id", "")) == correlation_id:
            matched_echoes.append(item)
    matched_echoes = matched_echoes[-max_items:]

    timestamps: list[str] = []
    for bucket in (meta_decisions, meta_evaluations, policy_audits, matched_echoes):
        for row in bucket:
            ts = str(row.get("timestamp", "") or row.get("created_at", ""))
            if ts:
                timestamps.append(ts)

    summary = {
        "correlation_id": correlation_id,
        "data_dir": str(data_dir),
        "counts": {
            "metacognitive_decisions": len(meta_decisions),
            "metacognitive_evaluations": len(meta_evaluations),
            "echo_memories": len(matched_echoes),
            "policy_audit": len(policy_audits),
        },
        "first_timestamp": min(timestamps) if timestamps else None,
        "last_timestamp": max(timestamps) if timestamps else None,
    }

    return {
        "summary": summary,
        "metacognitive_decisions": meta_decisions,
        "metacognitive_evaluations": meta_evaluations,
        "echo_memories": matched_echoes,
        "policy_audit": policy_audits,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trace personality decision chain by correlation id")
    parser.add_argument("--correlation-id", required=True, help="Correlation id to trace (e.g. dec_12_xxx)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Personality data directory")
    parser.add_argument("--max-items", type=int, default=50, help="Max rows per section")
    parser.add_argument("--output", type=Path, default=None, help="Optional output JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    max_items = max(1, int(args.max_items))
    payload = collect_correlation_trace(
        data_dir=args.data_dir,
        correlation_id=str(args.correlation_id),
        max_items=max_items,
    )

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"[OK] wrote trace report: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
