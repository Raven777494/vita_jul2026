"""Chat processing latency metrics for SLO tracking (P4-3).

Histogram `vita_chat_processing_seconds` labels hub turns as normal or crisis
for p95 comparison in Grafana / VictoriaMetrics.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import Histogram

from app.metrics.crisis_metrics import CrisisSignalSnapshot, is_crisis_signal

CHAT_PROCESSING_SECONDS = Histogram(
    "vita_chat_processing_seconds",
    "EmotionalSafetyHub process_user_input duration in seconds",
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


def record_chat_processing_seconds(*, path: str, duration_seconds: float) -> None:
    """Observe hub processing duration (path: normal | crisis)."""
    label = path if path in _VALID_PATHS else "normal"
    elapsed = max(float(duration_seconds), 0.0)
    CHAT_PROCESSING_SECONDS.labels(path=label).observe(elapsed)
