#!/usr/bin/env python3
"""Record daily P5 steady-state monitoring for go-live 2.4 (7-day gate).

Runs verify_p5_monitoring.py checks (focus: steady-state missed=0) and appends
one JSON line per calendar day to a local record file (gitignored under logs/).

Usage:
    python scripts/observability/record_mon_steady_state.py
    python scripts/observability/record_mon_steady_state.py --record-file D:/ops/MON-RECORD.jsonl
    python scripts/observability/record_mon_steady_state.py --required-days 7 --json

External ops archive: copy the record file or daily JSON lines to encrypted
storage (MON-RECORD-YYYY-MM-NNN). Do not commit record files to git.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.observability.verify_p5_monitoring import run_verification


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_record_path() -> Path:
    return _project_root() / "logs" / "mon-steady-state-record.jsonl"


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _steady_state_ok(report) -> bool:
    for check in report.checks:
        if check.name == "steady-state missed interceptions":
            return check.ok
    return False


def _steady_state_detail(report) -> str:
    for check in report.checks:
        if check.name == "steady-state missed interceptions":
            return check.detail
    return "n/a"


def _merge_day_entry(
    entries: list[dict[str, Any]],
    new_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep one entry per UTC date; latest run for that date wins."""
    date = new_entry["date"]
    without = [e for e in entries if e.get("date") != date]
    without.append(new_entry)
    without.sort(key=lambda e: e.get("date", ""))
    return without


def summarize_entries(
    entries: list[dict[str, Any]],
    *,
    required_days: int,
) -> dict[str, Any]:
    """Count consecutive passing calendar days ending on the latest recorded date."""
    if not entries:
        return {
            "days_recorded": 0,
            "days_passed": 0,
            "required_days": required_days,
            "gate_met": False,
            "last_dates": [],
        }
    by_date: dict[str, bool] = {}
    for entry in entries:
        by_date[entry["date"]] = bool(entry.get("ok"))

    dates = sorted(by_date.keys())
    latest = date.fromisoformat(dates[-1])
    streak = 0
    current = latest
    trailing: list[dict[str, Any]] = []
    while True:
        key = current.isoformat()
        if key not in by_date:
            break
        trailing.insert(0, {"date": key, "ok": by_date[key]})
        if not by_date[key]:
            break
        streak += 1
        current -= timedelta(days=1)

    return {
        "days_recorded": len(trailing),
        "days_passed": streak,
        "required_days": required_days,
        "gate_met": streak >= required_days,
        "last_dates": trailing[-required_days:] if len(trailing) > required_days else trailing,
    }


def record_daily_steady_state(
    *,
    record_file: Path,
    environment: str,
    required_days: int,
    api_metrics_url: str,
    vm_url: str,
    grafana_url: str,
    victorialogs_url: str,
    steady_state_window: str,
    skip_grafana: bool,
    skip_vm: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = run_verification(
        api_metrics_url=api_metrics_url,
        vm_base=vm_url,
        grafana_base=grafana_url,
        vl_base=victorialogs_url,
        skip_steady_state=False,
        skip_grafana=skip_grafana,
        skip_vm=skip_vm,
        steady_state_window=steady_state_window,
    )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entry: dict[str, Any] = {
        "record_type": "MON-STEADY-STATE",
        "date": _utc_date(),
        "timestamp_utc": now,
        "environment": environment,
        "ok": _steady_state_ok(report),
        "verify_ok": report.ok,
        "steady_state_detail": _steady_state_detail(report),
        "verify_checks_passed": sum(1 for c in report.checks if c.ok),
        "verify_checks_total": len(report.checks),
    }

    record_file.parent.mkdir(parents=True, exist_ok=True)
    merged = _merge_day_entry(_load_entries(record_file), entry)
    record_file.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in merged) + "\n",
        encoding="utf-8",
    )
    summary = summarize_entries(merged, required_days=required_days)
    return entry, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record daily MON steady-state for go-live 2.4"
    )
    parser.add_argument(
        "--record-file",
        type=Path,
        default=None,
        help="JSONL record path (default: logs/mon-steady-state-record.jsonl)",
    )
    parser.add_argument(
        "--environment",
        default="HSS D:\\vita",
        help="Environment label stored in record",
    )
    parser.add_argument("--required-days", type=int, default=7)
    parser.add_argument("--api-metrics-url", default="http://127.0.0.1:8080/metrics")
    parser.add_argument("--vm-url", default="http://127.0.0.1:8428")
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3001")
    parser.add_argument("--victorialogs-url", default="http://127.0.0.1:9428")
    parser.add_argument("--steady-state-window", default="15m")
    parser.add_argument("--skip-grafana", action="store_true")
    parser.add_argument("--skip-vm", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    record_path = args.record_file or _default_record_path()
    entry, summary = record_daily_steady_state(
        record_file=record_path,
        environment=args.environment,
        required_days=args.required_days,
        api_metrics_url=args.api_metrics_url,
        vm_url=args.vm_url,
        grafana_url=args.grafana_url,
        victorialogs_url=args.victorialogs_url,
        steady_state_window=args.steady_state_window,
        skip_grafana=args.skip_grafana,
        skip_vm=args.skip_vm,
    )

    payload = {"today": entry, "summary": summary, "record_file": str(record_path)}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("[INFO] MON steady-state daily record (go-live 2.4)")
        print(f"  [OK] record file: {record_path}")
        print(
            f"  [{'OK' if entry['ok'] else 'FAIL'}] today {entry['date']}: "
            f"{entry['steady_state_detail']}"
        )
        print(
            f"  [INFO] 7-day gate: {summary['days_passed']}/{summary['required_days']} "
            f"days passed (recorded {summary['days_recorded']})"
        )
        if summary["gate_met"]:
            print("[OK] 7-day steady-state gate met")
        else:
            remaining = summary["required_days"] - summary["days_passed"]
            print(f"[INFO] gate not met — need {remaining} more passing day(s)")

    return 0 if entry["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
