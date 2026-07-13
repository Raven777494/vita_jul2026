"""Tests for MON steady-state 7-day record script."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.observability.record_mon_steady_state import (
    _merge_day_entry,
    summarize_entries,
)


def test_merge_day_entry_replaces_same_date() -> None:
    existing = [{"date": "2026-07-12", "ok": False}]
    new = {"date": "2026-07-12", "ok": True}
    merged = _merge_day_entry(existing, new)
    assert len(merged) == 1
    assert merged[0]["ok"] is True


def test_summarize_entries_gate_not_met_until_seven_consecutive_days() -> None:
    entries = [
        {"date": f"2026-07-{d:02d}", "ok": True}
        for d in range(1, 6)
    ]
    summary = summarize_entries(entries, required_days=7)
    assert summary["days_passed"] == 5
    assert summary["gate_met"] is False


def test_summarize_entries_gate_met_with_seven_consecutive_days() -> None:
    entries = [
        {"date": f"2026-07-{d:02d}", "ok": True}
        for d in range(1, 8)
    ]
    summary = summarize_entries(entries, required_days=7)
    assert summary["days_passed"] == 7
    assert summary["gate_met"] is True


def test_summarize_entries_gap_breaks_streak() -> None:
    entries = [
        {"date": "2026-07-01", "ok": True},
        {"date": "2026-07-03", "ok": True},
        {"date": "2026-07-04", "ok": True},
    ]
    summary = summarize_entries(entries, required_days=7)
    assert summary["days_passed"] == 2
    assert summary["gate_met"] is False


def test_summarize_entries_one_fail_breaks_streak() -> None:
    entries = [{"date": f"2026-07-{d:02d}", "ok": True} for d in range(1, 7)]
    entries.append({"date": "2026-07-07", "ok": False})
    summary = summarize_entries(entries, required_days=7)
    assert summary["days_passed"] == 0
    assert summary["gate_met"] is False


def test_record_script_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts/observability/record_mon_steady_state.py").is_file()
    assert (root / "docs/operations/mon-steady-state-7d.md").is_file()
