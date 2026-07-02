"""Engine7B three-tier runtime architecture.

Platform Engine  — docker-compose (PostgreSQL, Redis)
Compute Engine   — seele_v8_5.py (LLM inference, GPU/VRAM)
Logic Engine     — app/orchestrator.py (conversation pipeline)
"""

from app.engines.registry import collect_three_engine_health
from app.engines.types import EngineState, EngineTier

__all__ = [
    "EngineState",
    "EngineTier",
    "collect_three_engine_health",
]
