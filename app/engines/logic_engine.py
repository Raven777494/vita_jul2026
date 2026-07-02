"""Logic Engine — conversation pipeline, safety, personality (Vita Orchestrator).

Owns: Orchestrator, PersonalityModule, Navigator, safety gates, turn routing.
Does not own: LLM process deployment, PostgreSQL/Redis containers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.engines.types import ComponentStatus, EngineHealthReport, EngineState, EngineTier

logger = logging.getLogger("vita.engines.logic")

ROLE = "Logic Engine"
OWNER = "app/orchestrator.py + app/main.py (L3-L6)"


def probe_logic_engine(
    *,
    orchestrator_ready: bool,
    components: Optional[Dict[str, bool]] = None,
) -> EngineHealthReport:
    """Probe logic-layer components supplied by app.main at runtime."""
    component_map = components or {}
    statuses: list[ComponentStatus] = []

    for name, is_ok in component_map.items():
        statuses.append(
            ComponentStatus(
                name=name,
                status="ok" if is_ok else "down",
                detail="initialized" if is_ok else "not_initialized",
            )
        )

    orchestrator_ready = orchestrator_ready or component_map.get("orchestrator", False)
    personality_ok = component_map.get("personality_module", False)
    navigator_ok = component_map.get("navigator", False)

    if orchestrator_ready and personality_ok:
        state = EngineState.READY
        summary = "Logic layer ready (Orchestrator + PersonalityModule)"
    elif orchestrator_ready:
        state = EngineState.DEGRADED
        summary = "Logic layer degraded (Orchestrator up; PersonalityModule missing)"
    elif any(component_map.values()):
        state = EngineState.DEGRADED
        summary = "Logic layer degraded (partial initialization)"
    else:
        state = EngineState.DOWN
        summary = "Logic layer down (Orchestrator not ready)"

    return EngineHealthReport(
        tier=EngineTier.LOGIC,
        role=ROLE,
        owner=OWNER,
        state=state,
        components=statuses,
        summary=summary,
    )
