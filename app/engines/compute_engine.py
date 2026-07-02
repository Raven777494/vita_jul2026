"""Compute Engine — GPU/CPU inference and LLM process lifecycle (Seele).

Owns: LLM HTTP services on ports 8081-8085, VRAM budget, Seele meta controller.
Does not own: conversation routing, personality anchoring, DB schema.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.config import config
from app.engines.types import ComponentStatus, EngineHealthReport, EngineState, EngineTier
from app.utils.llm_health import probe_llm_service
from hardware_profile_loader import get_llm_compute_health

logger = logging.getLogger("vita.engines.compute")

ROLE = "Compute Engine"
OWNER = "seele_v8_5.py (SeeleUnifiedOrchestrator)"


def _probe_all_llm_services() -> Tuple[list[ComponentStatus], int, int]:
    components: list[ComponentStatus] = []
    services = config.get_startup_llm_services()
    available = 0

    for label, url in services.items():
        ok, detail = probe_llm_service(url, timeout=3.0, api_key=getattr(config, "API_KEY", None))
        if ok:
            available += 1
        components.append(
            ComponentStatus(
                name=label,
                status="ok" if ok else "down",
                detail=detail,
                metadata={"url": url},
            )
        )

    return components, available, len(services)


async def probe_compute_engine(
    meta_controller_enabled: Optional[bool] = None,
) -> EngineHealthReport:
    components, available, total = _probe_all_llm_services()

    meta_enabled = (
        meta_controller_enabled
        if meta_controller_enabled is not None
        else getattr(config, "SEELE_META_CONTROLLER_ENABLED", False)
    )
    if meta_enabled:
        meta_status = "down"
        meta_detail = "disabled"
        try:
            from app.utils.seele_meta_client import meta_controller_reachable

            meta_ok, meta_detail = await meta_controller_reachable(timeout=2.0)
            meta_status = "ok" if meta_ok else "down"
        except Exception as exc:
            meta_detail = str(exc)
        components.append(
            ComponentStatus(
                name="seele_meta_controller",
                status=meta_status,
                detail=meta_detail,
                metadata={"url": getattr(config, "SEELE_META_CONTROLLER_URL", "")},
            )
        )

    compute_health = get_llm_compute_health()
    main_ok = any(c.name == "Main-LLM (Soul)" and c.status == "ok" for c in components)

    if available == total and main_ok:
        state = EngineState.READY
        summary = f"Compute layer ready ({available}/{total} LLM services)"
    elif main_ok and available > 0:
        state = EngineState.DEGRADED
        summary = f"Compute layer degraded ({available}/{total} LLM services; main LLM up)"
    elif available > 0:
        state = EngineState.DEGRADED
        summary = f"Compute layer degraded ({available}/{total}; main LLM down)"
    else:
        state = EngineState.DOWN
        summary = "Compute layer down (no LLM services reachable)"

    report = EngineHealthReport(
        tier=EngineTier.COMPUTE,
        role=ROLE,
        owner=OWNER,
        state=state,
        components=components,
        summary=summary,
    )
    report.components.append(
        ComponentStatus(
            name="vram_budget",
            status="ok" if compute_health.get("loaded") else "unknown",
            detail=f"budget={compute_health.get('vram_budget_mb')}MB reserve={compute_health.get('vram_reserve_mb')}MB",
            metadata=compute_health,
        )
    )
    return report
