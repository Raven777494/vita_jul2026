"""Crisis interception metrics for VITA safety hub.

Definitions (P2-C):
  crisis_signal: risk_level >= CRISIS_SIGNAL_THRESHOLD, crisis keywords present,
                 or suicidal/self-harm indicators > 0.
  intercepted:   signal present AND final user-facing text passes companion policy
                 AND processing succeeded.
  missed:        signal present AND NOT intercepted.

Prometheus counters/gauge are scraped at GET /metrics (VictoriaMetrics).
Structured events ship to VictoriaLogs (log_type=crisis) for LogsQL alerts.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from prometheus_client import Counter, Gauge

from app.clinical.companion_language_policy import validate_user_facing_text
from app.config import config
from app.logger import get_crisis_logger

_crisis_logger = get_crisis_logger()
_lock = threading.Lock()

CRISIS_SIGNALS_TOTAL = Counter(
    "vita_crisis_signals_total",
    "Crisis signals detected by EmotionalSafetyHub",
    ["risk_band"],
)

CRISIS_INTERCEPTED_TOTAL = Counter(
    "vita_crisis_intercepted_total",
    "Crisis signals successfully intercepted (companion-safe outcome)",
)

CRISIS_MISSED_TOTAL = Counter(
    "vita_crisis_missed_total",
    "Crisis signals not intercepted (unsafe or failed outcome)",
)

CRISIS_INTERCEPTION_RATE = Gauge(
    "vita_crisis_interception_rate",
    "Ratio intercepted/signals (1.0 when no signals yet)",
)

_internal_signal_count = 0
_internal_intercepted_count = 0


@dataclass(frozen=True)
class CrisisSignalSnapshot:
    """Minimal risk fields for metric recording without importing hub types."""

    risk_level: int
    crisis_keywords: tuple[str, ...]
    suicidal_indicators: int = 0
    self_harm_indicators: int = 0


def _risk_band(level: int) -> str:
    if level >= 5:
        return "critical"
    if level >= 4:
        return "high"
    if level >= 3:
        return "elevated"
    return "moderate"


def is_crisis_signal(snapshot: CrisisSignalSnapshot) -> bool:
    threshold = int(getattr(config, "CRISIS_SIGNAL_THRESHOLD", 3))
    if snapshot.risk_level >= threshold:
        return True
    if snapshot.crisis_keywords:
        return True
    if snapshot.suicidal_indicators > 0 or snapshot.self_harm_indicators > 0:
        return True
    return False


def _is_response_intercepted(response_text: str, *, success: bool) -> bool:
    if not success:
        return False
    if not response_text or not response_text.strip():
        return False
    ok, _issues = validate_user_facing_text(response_text)
    return ok


def _update_rate_gauge() -> None:
    if _internal_signal_count == 0:
        CRISIS_INTERCEPTION_RATE.set(1.0)
        return
    CRISIS_INTERCEPTION_RATE.set(
        _internal_intercepted_count / _internal_signal_count
    )


def crisis_interception_rate() -> float:
    """Current in-process interception rate (for tests and health export)."""
    with _lock:
        if _internal_signal_count == 0:
            return 1.0
        return _internal_intercepted_count / _internal_signal_count


def record_crisis_interception_outcome(
    *,
    risk_assessment: Any,
    response_text: str,
    escalated: bool,
    fallback_used: bool,
    success: bool,
    user_id: str = "",
    session_id: str = "",
) -> Optional[str]:
    """Record metrics and VictoriaLogs event when a crisis signal was present.

    Returns outcome string ('intercepted' | 'missed') or None if not a crisis signal.
    """
    if risk_assessment is None:
        return None

    snapshot = CrisisSignalSnapshot(
        risk_level=int(getattr(risk_assessment, "risk_level", 1)),
        crisis_keywords=tuple(getattr(risk_assessment, "crisis_keywords", []) or []),
        suicidal_indicators=int(getattr(risk_assessment, "suicidal_indicators", 0)),
        self_harm_indicators=int(getattr(risk_assessment, "self_harm_indicators", 0)),
    )

    if not is_crisis_signal(snapshot):
        return None

    intercepted = _is_response_intercepted(response_text, success=success)
    outcome = "intercepted" if intercepted else "missed"

    with _lock:
        global _internal_signal_count, _internal_intercepted_count
        _internal_signal_count += 1
        if intercepted:
            _internal_intercepted_count += 1
        _update_rate_gauge()

    CRISIS_SIGNALS_TOTAL.labels(risk_band=_risk_band(snapshot.risk_level)).inc()
    if intercepted:
        CRISIS_INTERCEPTED_TOTAL.inc()
    else:
        CRISIS_MISSED_TOTAL.inc()

    payload: Dict[str, Any] = {
        "event_type": "crisis_interception",
        "outcome": outcome,
        "risk_level": snapshot.risk_level,
        "risk_band": _risk_band(snapshot.risk_level),
        "escalated": bool(escalated),
        "fallback_used": bool(fallback_used),
        "success": bool(success),
        "crisis_keyword_count": len(snapshot.crisis_keywords),
        "user_id": user_id or "unknown",
        "session_id": session_id or "unknown",
    }
    _emit_crisis_log_event(payload)
    return outcome


def _emit_crisis_log_event(payload: Dict[str, Any]) -> None:
    """Ship structured crisis metric to crisis.log / VictoriaLogs (no message content)."""
    message = json.dumps(payload, ensure_ascii=False)
    record = _crisis_logger.makeRecord(
        _crisis_logger.name,
        logging.WARNING,
        __file__,
        0,
        message,
        (),
        None,
    )
    vita_fields = {
        "event_type": payload.get("event_type", "crisis_interception"),
        "outcome": payload.get("outcome", "unknown"),
        "risk_level": payload.get("risk_level"),
        "risk_band": payload.get("risk_band"),
        "escalated": payload.get("escalated"),
    }
    setattr(record, "vita_fields", vita_fields)
    _crisis_logger.handle(record)


def reset_crisis_metrics_for_tests() -> None:
    """Reset in-process counters (Prometheus registry is process-global)."""
    global _internal_signal_count, _internal_intercepted_count
    with _lock:
        _internal_signal_count = 0
        _internal_intercepted_count = 0
        CRISIS_INTERCEPTION_RATE.set(1.0)
