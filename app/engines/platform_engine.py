"""Platform Engine — persistence and cache infrastructure (Docker services).

Owns: PostgreSQL, Redis.
Does not own: LLM processes, conversation routing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import config
from app.engines.types import ComponentStatus, EngineHealthReport, EngineState, EngineTier

logger = logging.getLogger("vita.engines.platform")

ROLE = "Platform Engine"
OWNER = "docker-compose.yml (vita-postgres: pgvector + AGE + pg_cron, redis)"


def probe_platform_engine(
    redis_client: Optional[Any] = None,
) -> EngineHealthReport:
    components: list[ComponentStatus] = []

    db_ok = False
    db_detail = "not_checked"
    installed_ext: dict[str, str] = {}
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        engine = create_engine(
            config.DATABASE_URL,
            poolclass=NullPool,
            connect_args={"connect_timeout": config.DB_POOL_TIMEOUT},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            ext_rows = conn.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension "
                    "WHERE extname IN ('vector', 'age', 'pg_cron') "
                    "ORDER BY extname"
                )
            ).fetchall()
        db_ok = True
        db_detail = "connected"
        installed_ext = {row[0]: row[1] for row in ext_rows}
    except Exception as exc:
        db_detail = str(exc)
        logger.debug("Platform DB probe failed: %s", exc)

    components.append(
        ComponentStatus(
            name="postgresql",
            status="ok" if db_ok else "down",
            detail=db_detail,
            metadata={"host": config.DB_HOST, "port": config.DB_PORT, "database": config.DB_NAME},
        )
    )

    if db_ok:
        for ext_name in ("vector", "age", "pg_cron"):
            if ext_name in installed_ext:
                components.append(
                    ComponentStatus(
                        name=f"pg_extension:{ext_name}",
                        status="ok",
                        detail=f"v{installed_ext[ext_name]}",
                    )
                )
            else:
                components.append(
                    ComponentStatus(
                        name=f"pg_extension:{ext_name}",
                        status="degraded" if ext_name != "vector" else "down",
                        detail="not_installed",
                    )
                )

    redis_ok = False
    redis_detail = "not_checked"
    if redis_client is not None:
        try:
            redis_client.ping()
            redis_ok = True
            redis_detail = "connected"
        except Exception as exc:
            redis_detail = str(exc)
    else:
        try:
            import redis

            client = redis.from_url(
                config.REDIS_URL,
                socket_connect_timeout=config.REDIS_SOCKET_CONNECT_TIMEOUT,
                socket_timeout=config.REDIS_SOCKET_TIMEOUT,
            )
            client.ping()
            redis_ok = True
            redis_detail = "connected"
            client.close()
        except Exception as exc:
            redis_detail = str(exc)

    components.append(
        ComponentStatus(
            name="redis",
            status="ok" if redis_ok else "degraded",
            detail=redis_detail,
            metadata={"url": config.REDIS_URL.split("@")[-1] if "@" in config.REDIS_URL else config.REDIS_URL},
        )
    )

    vlogs_ok = False
    vlogs_detail = "disabled"
    if config.ENABLE_VICTORIA_LOGS_SHIPPER and config.VICTORIA_LOGS_URL:
        try:
            import httpx

            with httpx.Client(timeout=config.VICTORIA_LOGS_TIMEOUT) as client:
                response = client.get(f"{config.VICTORIA_LOGS_URL}/health")
                vlogs_ok = response.status_code == 200
                vlogs_detail = "connected" if vlogs_ok else f"http_{response.status_code}"
        except Exception as exc:
            vlogs_detail = str(exc)
        components.append(
            ComponentStatus(
                name="victorialogs",
                status="ok" if vlogs_ok else "degraded",
                detail=vlogs_detail,
                metadata={"url": config.VICTORIA_LOGS_URL},
            )
        )

    if db_ok and redis_ok:
        state = EngineState.READY
        summary = "Platform layer ready (PostgreSQL + Redis)"
    elif db_ok:
        state = EngineState.DEGRADED
        summary = "PostgreSQL ready; Redis unavailable (cache degraded)"
    else:
        state = EngineState.DOWN
        summary = "Platform layer critical: database unreachable"

    return EngineHealthReport(
        tier=EngineTier.PLATFORM,
        role=ROLE,
        owner=OWNER,
        state=state,
        components=components,
        summary=summary,
    )
