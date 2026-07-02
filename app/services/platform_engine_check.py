"""Platform Engine verification (pgvector + Apache AGE + pg_cron).

Used by system_alignment_checker and startup_checks to confirm the app
connects to docker/postgres (vita-postgres), not a plain local PostgreSQL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

REQUIRED_EXTENSIONS: Tuple[str, ...] = ("vector", "age", "pg_cron")
AGE_GRAPH_NAME = "vita_memory_graph"
PGCRON_JOB_NAME = "clean-old-gsw-echoes"
EXPECTED_POSTGRES_IMAGE = "vita-postgres:pg16-vector-age-cron"


@dataclass
class PlatformEngineReport:
    ok: bool
    checked: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    db_host: str = ""
    db_port: str = ""
    db_name: str = ""
    server_version: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": list(self.checked),
            "issues": list(self.issues),
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "server_version": self.server_version,
        }


def _wrong_postgres_hint(host: str, port: str) -> str:
    return (
        f"Connected to {host}:{port} but Platform extensions are missing. "
        f"Start the Docker Postgres service: docker compose up -d postgres "
        f"(image {EXPECTED_POSTGRES_IMAGE}). "
        f"Ensure DB_HOST in config/.env.local is 127.0.0.1 when using the "
        f"published port 5432, and that no other PostgreSQL instance binds "
        f"5432 on this machine."
    )


def verify_platform_engine(
    db_manager: Any,
    *,
    require_age_graph: bool = True,
    require_pg_cron_job: bool = False,
) -> PlatformEngineReport:
    """Verify vector/age/pg_cron extensions and optional AGE graph presence."""
    from app.config import config

    report = PlatformEngineReport(
        ok=True,
        db_host=str(getattr(config, "DB_HOST", "")),
        db_port=str(getattr(config, "DB_PORT", "")),
        db_name=str(getattr(config, "DB_NAME", "")),
    )

    try:
        version_rows = db_manager.execute_query("SELECT version() AS version")
        if version_rows:
            report.server_version = str(version_rows[0].get("version", ""))[:120]
            report.checked.append(f"PostgreSQL reachable: {report.server_version[:60]}...")
    except Exception as exc:
        report.ok = False
        report.issues.append(f"Database query failed: {exc}")
        return report

    missing_extensions: List[str] = []
    for ext in REQUIRED_EXTENSIONS:
        rows = db_manager.execute_query(
            "SELECT extversion FROM pg_extension WHERE extname = :ext LIMIT 1",
            {"ext": ext},
        )
        if rows:
            version = rows[0].get("extversion", "?")
            report.checked.append(f"Extension {ext} present [OK] (v{version})")
        else:
            missing_extensions.append(ext)
            report.issues.append(f"Extension {ext} missing")

    if missing_extensions:
        report.ok = False
        report.issues.append(
            _wrong_postgres_hint(report.db_host, report.db_port)
        )
        return report

    if require_age_graph:
        graph_rows = db_manager.execute_query(
            "SELECT name FROM ag_catalog.ag_graph WHERE name = :graph_name LIMIT 1",
            {"graph_name": AGE_GRAPH_NAME},
        )
        if graph_rows:
            report.checked.append(f"AGE graph {AGE_GRAPH_NAME} present [OK]")
        else:
            report.ok = False
            report.issues.append(
                f"AGE graph {AGE_GRAPH_NAME} missing (run init-db/03-age-graph.sql "
                f"or restart app bootstrap)"
            )

    if require_pg_cron_job:
        job_rows = db_manager.execute_query(
            "SELECT jobid FROM cron.job WHERE jobname = :job_name LIMIT 1",
            {"job_name": PGCRON_JOB_NAME},
        )
        if job_rows:
            report.checked.append(f"pg_cron job {PGCRON_JOB_NAME} present [OK]")
        else:
            report.issues.append(
                f"pg_cron job {PGCRON_JOB_NAME} not scheduled (non-fatal; "
                f"app bootstrap or init-db/04-pg-cron-jobs.sql)"
            )

    return report


def _is_ci_without_platform_db() -> bool:
    """True when CI has no Docker Platform Engine Postgres (GitHub Actions or explicit opt-out)."""
    if os.getenv("DB_PLATFORM_ENGINE_REQUIRED", "true").lower() != "true":
        return True
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true"


def verify_platform_engine_or_skip(
    db_manager: Optional[Any] = None,
    *,
    require_age_graph: bool = True,
) -> Tuple[str, PlatformEngineReport]:
    """Return (status, report) where status is PASS | FAIL | SKIP."""
    if db_manager is None:
        try:
            from app.services.db_manager import db_manager as default_db
            db_manager = default_db
        except Exception as exc:
            report = PlatformEngineReport(ok=False, issues=[f"Cannot import db_manager: {exc}"])
            return "SKIP", report

    try:
        report = verify_platform_engine(db_manager, require_age_graph=require_age_graph)
    except Exception as exc:
        report = PlatformEngineReport(ok=False, issues=[f"Platform Engine check error: {exc}"])
        return "SKIP", report

    if report.ok:
        return "PASS", report
    if _is_ci_without_platform_db():
        return "SKIP", report
    return "FAIL", report
