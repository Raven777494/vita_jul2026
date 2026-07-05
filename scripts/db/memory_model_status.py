#!/usr/bin/env python3
"""Report memory model store status per ADR-002 (P4-4).

Prints row counts for primary relational paths and confirms AGE graph
provisioning without requiring cypher writes.

Usage:
    python scripts/db/memory_model_status.py
    python scripts/db/memory_model_status.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fetch_status(db_manager: Any, config: Any) -> tuple[Dict[str, Any], List[str]]:
    from app.services.platform_engine_check import AGE_GRAPH_NAME, _probe_database_connection

    errors: List[str] = []
    conn_error = _probe_database_connection(config)
    if conn_error:
        errors.append(conn_error)

    status: Dict[str, Any] = {
        "adr": "docs/architecture/adr-002-memory-model.md",
        "primary_path": "relational (gsw_eternal_echoes + memory_graph)",
        "age_graph_mode": "read-only reserve",
        "database_reachable": conn_error is None,
        "tables": {},
        "age_graph": {"name": AGE_GRAPH_NAME, "provisioned": False},
    }

    if conn_error:
        return status, errors

    for table in ("gsw_eternal_echoes", "memory_graph"):
        rows = db_manager.execute_query(f"SELECT COUNT(*) AS cnt FROM {table}")
        if not rows:
            errors.append(f"Could not read row count for {table} (query returned no rows)")
            status["tables"][table] = {"error": "query returned no rows"}
            continue
        if "cnt" not in rows[0]:
            errors.append(f"Unexpected result shape for {table}: {rows[0]!r}")
            status["tables"][table] = {"error": "unexpected result shape"}
            continue
        status["tables"][table] = int(rows[0]["cnt"])

    graph_rows = db_manager.execute_query(
        "SELECT name FROM ag_catalog.ag_graph WHERE name = :graph_name LIMIT 1",
        {"graph_name": AGE_GRAPH_NAME},
    )
    if graph_rows:
        status["age_graph"]["provisioned"] = True
    else:
        status["age_graph"]["provisioned"] = False

    return status, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Memory model status (ADR-002)")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args(argv)

    project_root = _project_root()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from app.config import config
        from app.services.db_manager import db_manager
    except Exception as exc:
        print(f"[FAIL] Cannot import application modules: {exc}", file=sys.stderr)
        return 1

    payload, errors = _fetch_status(db_manager, config)

    if args.json:
        payload["errors"] = errors
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if not errors else 1

    print("[INFO] Memory model status (ADR-002)")
    print(f"  Primary path: {payload['primary_path']}")
    print(f"  AGE mode: {payload['age_graph_mode']}")
    print(f"  Database reachable: {'yes' if payload.get('database_reachable') else 'no'}")
    for table, count in payload.get("tables", {}).items():
        print(f"  {table}: {count}")
    age = payload.get("age_graph", {})
    prov = "yes" if age.get("provisioned") else "no"
    print(f"  AGE graph {age.get('name')!r} provisioned: {prov}")

    if errors:
        print("[FAIL] memory_model_status could not complete:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("[OK] memory_model_status complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
