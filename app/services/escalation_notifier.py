"""Escalation notification backends (P4-2 / TD-005).

Pluggable notifier for risk level 4-5 internal escalation events.
Webhook URL is read from ESCALATION_WEBHOOK_URL (env / GitHub Encrypted Secrets).
Never hard-code webhook URLs or credentials in this module.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

logger = logging.getLogger("vita.escalation_notifier")


@dataclass(frozen=True)
class EscalationNotification:
    user_id: str
    session_id: str
    risk_level: int
    walker_score: float
    action: str = "ESCALATION_REQUIRED"
    timestamp: str = ""

    def to_log_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_webhook_dict(self, *, user_id_hash: str) -> dict[str, Any]:
        """Payload for external webhook (no raw user_id)."""
        return {
            "timestamp": self.timestamp,
            "user_id_hash": user_id_hash,
            "session_id": self.session_id,
            "risk_level": self.risk_level,
            "walker_score": round(float(self.walker_score), 4),
            "action": self.action,
            "source": "vita_escalation_notifier",
        }


class EscalationBackend(Protocol):
    async def send(self, event: EscalationNotification) -> bool:
        ...


class LogEscalationBackend:
    """Always-on backend: structured warning to application log."""

    async def send(self, event: EscalationNotification) -> bool:
        logger.warning("[ESCALATION] %s", json.dumps(event.to_log_dict(), ensure_ascii=False))
        return True


class WebhookEscalationBackend:
    """POST JSON to ESCALATION_WEBHOOK_URL when configured."""

    def __init__(self, webhook_url: str, timeout_seconds: float = 10.0) -> None:
        self.webhook_url = webhook_url.strip()
        self.timeout_seconds = timeout_seconds

    async def send(self, event: EscalationNotification) -> bool:
        if not self.webhook_url:
            return False
        try:
            import httpx

            from app.utils.audit_logger import audit_log

            payload = event.to_webhook_dict(user_id_hash=audit_log._hash_pii(event.user_id))
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "VITA-Escalation/1.0"},
                )
            if response.status_code >= 400:
                logger.error(
                    "[ESCALATION] Webhook HTTP %s for session_id=%s",
                    response.status_code,
                    event.session_id,
                )
                return False
            logger.info(
                "[ESCALATION] Webhook delivered session_id=%s risk_level=%s",
                event.session_id,
                event.risk_level,
            )
            return True
        except Exception as exc:
            logger.error("[ESCALATION] Webhook failed session_id=%s: %s", event.session_id, exc)
            return False


class EscalationNotifier:
    """Fan-out escalation events to configured backends."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        webhook_url: str = "",
        backends: Optional[list[EscalationBackend]] = None,
    ) -> None:
        self.enabled = enabled
        if backends is not None:
            self._backends = backends
        else:
            configured: list[EscalationBackend] = [LogEscalationBackend()]
            if webhook_url:
                configured.append(WebhookEscalationBackend(webhook_url))
            self._backends = configured

    async def notify(
        self,
        user_id: str,
        session_id: str,
        risk_level: int,
        walker_score: float,
        *,
        action: str = "ESCALATION_REQUIRED",
    ) -> dict[str, bool]:
        """Send escalation notification; return per-backend success map."""
        if not self.enabled:
            return {"disabled": True}

        event = EscalationNotification(
            user_id=user_id,
            session_id=session_id,
            risk_level=int(risk_level),
            walker_score=float(walker_score),
            action=action,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )
        results: dict[str, bool] = {}
        for index, backend in enumerate(self._backends):
            name = type(backend).__name__
            key = f"{name}_{index}"
            results[key] = await backend.send(event)
        return results


_notifier: Optional[EscalationNotifier] = None


def get_escalation_notifier() -> EscalationNotifier:
    global _notifier
    if _notifier is None:
        from app.config import config

        _notifier = EscalationNotifier(
            enabled=config.ESCALATION_NOTIFIER_ENABLED,
            webhook_url=config.ESCALATION_WEBHOOK_URL,
        )
    return _notifier


def reset_escalation_notifier_for_tests(notifier: Optional[EscalationNotifier] = None) -> None:
    """Reset singleton (tests only)."""
    global _notifier
    _notifier = notifier
