"""Tests for scripts/db/retention_batch.py (P4-1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from scripts.db.retention_batch import (
    RETENTION_STEPS,
    compute_cutoff,
    count_matching_rows,
    run_retention,
)


class FakeDb:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict | None]] = []
        self.updates: list[tuple[str, dict | None]] = []
        self.counts: dict[str, int] = {}
        self.delete_results: dict[str, int] = {}

    def execute_query(self, query_str: str, params: dict | None = None) -> list[dict[str, Any]]:
        self.queries.append((query_str, params))
        for table, n in self.counts.items():
            if f"FROM {table}" in query_str:
                return [{"n": n}]
        return [{"n": 0}]

    def execute_update(self, query_str: str, params: dict | None = None) -> int:
        self.updates.append((query_str, params))
        for table, n in self.delete_results.items():
            if query_str.startswith(f"DELETE FROM {table}"):
                return n
        return 0


def test_compute_cutoff_uses_naive_utc() -> None:
    now = datetime(2026, 7, 5, 12, 0, 0)
    cutoff = compute_cutoff(90, now=now)
    assert cutoff == now - timedelta(days=90)
    assert cutoff.tzinfo is None


def test_retention_steps_include_core_session_tables() -> None:
    tables = {step.table for step in RETENTION_STEPS}
    assert tables == {
        "active_sessions",
        "turns",
        "session_history",
        "escalation_events",
    }


def test_run_retention_dry_run_does_not_delete() -> None:
    db = FakeDb()
    db.counts = {step.table: 3 for step in RETENTION_STEPS}
    logs: list[str] = []

    counts = run_retention(
        db,
        90,
        dry_run=True,
        now=datetime(2026, 7, 5),
        log=logs.append,
    )

    assert len(db.queries) == len(RETENTION_STEPS)
    assert db.updates == []
    assert all(v == 3 for v in counts.values())
    assert any("dry-run" in line for line in logs)


def test_run_retention_apply_deletes_in_step_order() -> None:
    db = FakeDb()
    db.counts = {
        "active_sessions": 2,
        "turns": 5,
        "session_history": 1,
        "escalation_events": 4,
    }
    db.delete_results = dict(db.counts)

    run_retention(db, 30, dry_run=False, now=datetime(2026, 1, 1))

    assert [step.table for step in RETENTION_STEPS] == [
        "active_sessions",
        "turns",
        "session_history",
        "escalation_events",
    ]
    deleted_tables = [
        q[0].split("DELETE FROM ", 1)[1].split(" ", 1)[0] for q in db.updates
    ]
    assert deleted_tables == [step.table for step in RETENTION_STEPS]


def test_count_matching_rows_returns_zero_on_empty_result() -> None:
    class EmptyDb:
        def execute_query(self, query_str: str, params: dict | None = None) -> list[dict]:
            return []

    assert count_matching_rows(EmptyDb(), RETENTION_STEPS[0], datetime(2020, 1, 1)) == 0
