"""Chat processing latency metrics for SLO tracking (P4-3).

Histogram `vita_chat_processing_seconds` labels each chat turn as normal or
crisis for p95 comparison in Grafana / VictoriaMetrics. Recorded from both the
runtime orchestrator path (`process_user_message_async`) and the
`EmotionalSafetyHub` path so SLO-2 / SLO-3 have live samples regardless of which
pipeline served the turn.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import Histogram

from app.metrics.crisis_metrics import CrisisSignalSnapshot, is_crisis_signal

CHAT_PROCESSING_SECONDS = Histogram(
    "vita_chat_processing_seconds",
    "Chat turn processing duration in seconds (orchestrator and safety hub)",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 15.0, 30.0, 60.0),
)

_VALID_PATHS = frozenset({"normal", "crisis"})


def resolve_processing_path(risk_assessment: Any) -> str:
    """Return metric path label for a completed hub turn."""
    if risk_assessment is None:
        return "normal"
    snapshot = CrisisSignalSnapshot(
        risk_level=int(getattr(risk_assessment, "risk_level", 1)),
        crisis_keywords=tuple(getattr(risk_assessment, "crisis_keywords", []) or []),
        suicidal_indicators=int(getattr(risk_assessment, "suicidal_indicators", 0)),
        self_harm_indicators=int(getattr(risk_assessment, "self_harm_indicators", 0)),
    )
    return "crisis" if is_crisis_signal(snapshot) else "normal"


def resolve_processing_path_from_risk_level(risk_level: int) -> str:
    """Return metric path label from a completed turn's integer risk level.

    Used by the orchestrator runtime path where only ``risk_level`` (not a full
    RiskAssessment object) is available. Threshold logic is shared with
    ``is_crisis_signal`` for consistency with crisis interception metrics.
    """
    snapshot = CrisisSignalSnapshot(
        risk_level=int(risk_level or 0),
        crisis_keywords=(),
    )
    return "crisis" if is_crisis_signal(snapshot) else "normal"


def record_chat_processing_seconds(*, path: str, duration_seconds: float) -> None:
    """Observe hub processing duration (path: normal | crisis)."""
    label = path if path in _VALID_PATHS else "normal"
    elapsed = max(float(duration_seconds), 0.0)
    CHAT_PROCESSING_SECONDS.labels(path=label).observe(elapsed)


def record_chat_processing_from_risk_level(
    *, risk_level: int, duration_seconds: float
) -> None:
    """Observe chat turn duration, deriving the path label from ``risk_level``."""
    record_chat_processing_seconds(
        path=resolve_processing_path_from_risk_level(risk_level),
        duration_seconds=duration_seconds,
    )
