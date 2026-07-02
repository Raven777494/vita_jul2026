"""Three-engine registry — aggregate Platform, Compute, and Logic health."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.engines.compute_engine import probe_compute_engine
from app.engines.logic_engine import probe_logic_engine
from app.engines.platform_engine import probe_platform_engine
from app.engines.types import EngineState, EngineTier


def _overall_state(states: list[EngineState]) -> EngineState:
    if any(s == EngineState.DOWN for s in states):
        if states[0] == EngineState.DOWN:
            return EngineState.DOWN
        return EngineState.DEGRADED
    if any(s == EngineState.DEGRADED for s in states):
        return EngineState.DEGRADED
    if all(s == EngineState.READY for s in states):
        return EngineState.READY
    return EngineState.UNKNOWN


async def collect_three_engine_health(
    *,
    redis_client: Any = None,
    orchestrator_ready: bool = False,
    logic_components: Optional[Dict[str, bool]] = None,
    meta_controller_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return unified health for Platform / Compute / Logic engines."""
    platform = probe_platform_engine(redis_client=redis_client)
    compute = await probe_compute_engine(meta_controller_enabled=meta_controller_enabled)
    logic = probe_logic_engine(
        orchestrator_ready=orchestrator_ready,
        components=logic_components,
    )

    reports = [platform, compute, logic]
    states = [r.state for r in reports]
    overall = _overall_state(states)

    startup_order = [
        {
            "step": 1,
            "engine": EngineTier.PLATFORM.value,
            "action": "docker compose up -d postgres redis",
            "owner": platform.owner,
        },
        {
            "step": 2,
            "engine": EngineTier.COMPUTE.value,
            "action": "python seele_v8_5.py --action deploy",
            "owner": compute.owner,
        },
        {
            "step": 3,
            "engine": EngineTier.LOGIC.value,
            "action": "python -m uvicorn app.main:app_instance --host 127.0.0.1 --port 8000",
            "owner": logic.owner,
        },
    ]

    return {
        "architecture": "three-engine",
        "overall_state": overall.value,
        "summary": (
            f"platform={platform.state.value}, "
            f"compute={compute.state.value}, "
            f"logic={logic.state.value}"
        ),
        "startup_order": startup_order,
        "engines": {
            EngineTier.PLATFORM.value: platform.to_dict(),
            EngineTier.COMPUTE.value: compute.to_dict(),
            EngineTier.LOGIC.value: logic.to_dict(),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
