"""Shared types for the three-engine architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EngineTier(str, Enum):
    PLATFORM = "platform"
    COMPUTE = "compute"
    LOGIC = "logic"


class EngineState(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class ComponentStatus:
    name: str
    status: str
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineHealthReport:
    tier: EngineTier
    role: str
    owner: str
    state: EngineState
    components: List[ComponentStatus] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "role": self.role,
            "owner": self.owner,
            "state": self.state.value,
            "summary": self.summary,
            "components": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    **({"metadata": c.metadata} if c.metadata else {}),
                }
                for c in self.components
            ],
        }
