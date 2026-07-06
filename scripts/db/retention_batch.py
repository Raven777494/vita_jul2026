#!/usr/bin/env python3
"""Batch retention for session-scoped conversation data (P4-1).

Purges rows older than SESSION_MAX_RETENTION_DAYS (default 90 from app.config):

  1. inactive active_sessions (is_active=false, last_updated_at) — CASCADE turns, risk_assessments
  2. turns (created_at) — old turns in still-active sessions
  3. session_history (COALESCE(ended_at, created_at))
  4. escalation_events (escalated_at) — no FK; cleaned by age

Does NOT purge users, psych_assessments, crisis_events, memory_graph, or gsw_eternal_echoes.
GSW echoes use pg_cron job clean-old-gsw-echoes (30 days).

Usage:
    python scripts/db/retention_batch.py --dry-run
    python scripts/db/retention_batch.py --apply
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class RetentionStep:
    table: str
    where: str
    label: str


# Apply order: sessions first so CASCADE removes dependent turns/risk_assessments.
RETENTION_STEPS: tuple[RetentionStep, ...] = (
    RetentionStep(
        "active_sessions",
        "is_active = false AND last_updated_at < :cutoff",
        "inactive sessions",
    ),
    RetentionStep(
        "turns",
        "created_at < :cutoff",
        "turns",
    ),
    RetentionStep(
        "session_history",
        "COALESCE(ended_at, created_at) < :cutoff",
        "session history archives",
    ),
    RetentionStep(
        "escalation_events",
        "escalated_at < :cutoff",
        "escalation events",
    ),
)


class DbExecutor(Protocol):
    def execute_query(self, query_str: str, params: dict | None = None) -> list[dict]:
        ...

    def execute_update(self, query_str: str, params: dict | None = None) -> int:
        ...


def compute_cutoff(retention_days: int, now: datetime | None = None) -> datetime:
    """Return naive UTC cutoff datetime matching db_manager DateTime columns."""
    ref = now or datetime.utcnow()
    if ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    return ref - timedelta(days=retention_days)


def count_matching_rows(db: DbExecutor, step: RetentionStep, cutoff: datetime) -> int:
    rows = db.execute_query(
        f"SELECT COUNT(*) AS n FROM {step.table} WHERE {step.where}",
        {"cutoff": cutoff},
    )
    if not rows:
        return 0
    return int(rows[0]["n"])


def delete_matching_rows(db: DbExecutor, step: RetentionStep, cutoff: datetime) -> int:
    return db.execute_update(
        f"DELETE FROM {step.table} WHERE {step.where}",
        {"cutoff": cutoff},
    )


def run_retention(
    db: DbExecutor,
    retention_days: int,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Count (dry-run) or delete (apply) retention-eligible rows per table."""
    emit = log or print
    cutoff = compute_cutoff(retention_days, now)
    counts: dict[str, int] = {}

    emit(f"[INFO] Retention window: {retention_days} days; cutoff (UTC naive): {cutoff.isoformat()}")
    emit(f"[INFO] Mode: {'dry-run' if dry_run else 'apply'}")

    for step in RETENTION_STEPS:
        matched = count_matching_rows(db, step, cutoff)
        counts[step.table] = matched
        emit(f"[INFO] {step.table} ({step.label}): {matched} row(s) eligible")

        if dry_run or matched == 0:
            continue

        deleted = delete_matching_rows(db, step, cutoff)
        emit(f"[INFO] {step.table}: deleted {deleted} row(s)")
        if deleted != matched:
            emit(
                f"[WARN] {step.table}: counted {matched} eligible but deleted {deleted} "
                "(possible concurrent delete or rowcount mismatch)"
            )

    total = sum(counts.values())
    emit(f"[INFO] Total eligible rows: {total}")
    return counts


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    parser = argparse.ArgumentParser(description="Session-scoped DB retention batch (P4-1)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Report row counts only (default path)")
    group.add_argument("--apply", action="store_true", help="Delete eligible rows")
    args = parser.parse_args(argv)

    from app.config import config
    from app.services.db_manager import DatabaseUpdateError, db_manager

    dry_run = not args.apply
    try:
        counts = run_retention(
            db_manager,
            config.SESSION_MAX_RETENTION_DAYS,
            dry_run=dry_run,
        )
    except DatabaseUpdateError:
        print("[FAIL] Retention batch aborted due to database update error", file=sys.stderr)
        return 1

    if all(n == 0 for n in counts.values()):
        emit = print
        emit("[OK] No rows eligible for retention purge")
    elif dry_run:
        print("[OK] Dry-run complete; re-run with --apply to delete")
    else:
        print("[OK] Retention batch applied")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
