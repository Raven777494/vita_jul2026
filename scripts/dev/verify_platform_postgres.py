#!/usr/bin/env python3
"""Verify local DB connection targets Docker Platform Postgres (AGE + pg_cron).

Usage:
    python scripts/dev/verify_platform_postgres.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from app.config import config
    from app.services.platform_engine_check import verify_platform_engine_or_skip

    print(f"[INFO] DB target: {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    print(f"[INFO] Expected image: {config.DB_PLATFORM_POSTGRES_IMAGE}")

    status, report = verify_platform_engine_or_skip(require_age_graph=True)

    for line in report.checked:
        print(f"[OK] {line}")
    for line in report.issues:
        print(f"[FAIL] {line}")

    if status == "PASS":
        print("[OK] Platform Engine verified")
        return 0
    if status == "SKIP":
        print("[SKIP] Database unreachable — run: docker compose --env-file config/.env.compose up -d postgres")
        return 2
    print("[FAIL] Wrong PostgreSQL instance or missing extensions")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
