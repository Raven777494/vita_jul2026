#!/usr/bin/env python3
"""Investigate missed crisis interceptions in VictoriaLogs (P5 steady-state).

Classifies missed events in a time window and flags likely pytest pollution.

Usage:
    python scripts/observability/investigate_missed_interceptions.py
    python scripts/observability/investigate_missed_interceptions.py --window 24h
    python scripts/observability/investigate_missed_interceptions.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MissedEvent:
    time: str
    user_id: str
    session_id: str
    risk_level: str
    risk_band: str
    source: str
    success: str
    fallback_used: str
    classification: str


def _http_post(url: str, body: str, timeout: float = 12.0) -> tuple[int, str]:
    data = body.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _classify_event(row: dict[str, Any]) -> str:
    source = str(row.get("source", "") or "")
    user_id = str(row.get("user_id", "") or "")
    session_id = str(row.get("session_id", "") or "")

    if source == "test":
        return "pytest_source_tag"
    if not source and user_id == "u2" and session_id == "s2":
        return "pytest_crisis_metrics_test"
    if not source and user_id == "unknown" and session_id == "unknown":
        return "likely_pytest_or_missing_ids"
    if source == "safety_hub":
        return "production_safety_hub"
    if source:
        return f"other_source:{source}"
    return "legacy_no_source"


def query_missed_events(vl_base: str, window: str) -> list[MissedEvent]:
    query = (
        f'_time:{window} service:"vita-api" log_type:"crisis" '
        'event_type:"crisis_interception" outcome:"missed" '
        "| fields _time, user_id, session_id, risk_level, risk_band, source, success, fallback_used"
    )
    url = f"{vl_base.rstrip('/')}/select/logsql/query"
    status, body = _http_post(url, f"query={urllib.parse.quote(query)}")
    if status != 200:
        raise RuntimeError(f"VictoriaLogs HTTP {status}: {body[:300]}")

    events: list[MissedEvent] = []
    for line in body.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        classification = _classify_event(row)
        events.append(
            MissedEvent(
                time=str(row.get("_time", "")),
                user_id=str(row.get("user_id", "")),
                session_id=str(row.get("session_id", "")),
                risk_level=str(row.get("risk_level", "")),
                risk_band=str(row.get("risk_band", "")),
                source=str(row.get("source", "")),
                success=str(row.get("success", "")),
                fallback_used=str(row.get("fallback_used", "")),
                classification=classification,
            )
        )
    return events


def query_production_missed_count(vl_base: str, window: str) -> int:
    query = (
        f'_time:{window} service:"vita-api" log_type:"crisis" '
        'event_type:"crisis_interception" outcome:"missed" source:"safety_hub" '
        "| stats count() as missed"
    )
    url = f"{vl_base.rstrip('/')}/select/logsql/query"
    status, body = _http_post(url, f"query={urllib.parse.quote(query)}")
    if status != 200:
        raise RuntimeError(f"VictoriaLogs HTTP {status}: {body[:300]}")
    for line in body.strip().splitlines():
        try:
            row = json.loads(line.strip())
            return int(row.get("missed", row.get("count", 0)))
        except json.JSONDecodeError:
            continue
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Investigate missed crisis interceptions")
    parser.add_argument("--victorialogs-url", default="http://127.0.0.1:9428")
    parser.add_argument("--window", default="15m")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        events = query_missed_events(args.victorialogs_url, args.window)
        production_missed = query_production_missed_count(
            args.victorialogs_url, args.window
        )
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "window": args.window,
            "total_missed": len(events),
            "production_missed": production_missed,
            "events": [e.__dict__ for e in events],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if production_missed == 0 else 1

    print(f"[INFO] Missed crisis interceptions (window={args.window})")
    print(f"  total in VL (any source): {len(events)}")
    print(f"  production (source=safety_hub): {production_missed}")

    if not events:
        print("[OK] No missed events in window")
        return 0

    print("[INFO] Event detail:")
    for event in events:
        print(
            f"  - {event.time} user={event.user_id} session={event.session_id} "
            f"risk={event.risk_level}/{event.risk_band} source={event.source or '(none)'} "
            f"[{event.classification}]"
        )

    pytest_like = [
        e
        for e in events
        if e.classification.startswith("pytest") or e.classification.startswith("likely_pytest")
    ]
    if pytest_like and production_missed == 0:
        print(
            "[WARN] All missed events appear to be pytest/local test pollution; "
            "steady-state uses source:safety_hub only"
        )
        print("[OK] No production missed interceptions in window")
        return 0

    if production_missed > 0:
        print(
            f"[FAIL] {production_missed} production missed interception(s) — "
            "see docs/operations/crisis-playbook.md",
            file=sys.stderr,
        )
        return 1

    print("[OK] No production missed interceptions in window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
