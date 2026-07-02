"""Single user-facing text gate for VITA (P3-3 / ADR-001).

All chat responses shown to users must pass through apply_user_facing_gate()
when emitted from the Logic Engine orchestrator path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

from app.clinical.companion_language_policy import (
    get_companion_reply,
    validate_user_facing_text,
)

logger = logging.getLogger("vita.companion_gate")


@dataclass(frozen=True)
class UserFacingGateResult:
    text: str
    sanitized: bool
    issues: Tuple[str, ...]
    fallback_tier: str


def _fallback_tier_for_risk(risk_level: int) -> str:
    if risk_level >= 5:
        return "critical"
    if risk_level >= 4:
        return "high_risk"
    if risk_level >= 2:
        return "medium_risk"
    return "fallback"


def apply_user_facing_gate(
    text: str,
    *,
    risk_level: int = 1,
    source: str = "unknown",
) -> UserFacingGateResult:
    """Validate user-visible text; replace with companion-safe reply if forbidden."""
    raw = (text or "").strip()
    tier = _fallback_tier_for_risk(int(risk_level or 1))

    if not raw:
        safe = get_companion_reply(tier)
        return UserFacingGateResult(
            text=safe,
            sanitized=True,
            issues=("empty_response",),
            fallback_tier=tier,
        )

    ok, issues = validate_user_facing_text(raw)
    if ok:
        return UserFacingGateResult(
            text=raw,
            sanitized=False,
            issues=tuple(),
            fallback_tier=tier,
        )

    safe = get_companion_reply(tier)
    logger.warning(
        "[COMPANION_GATE] Sanitized user-facing text from %s (risk=%s, issues=%s)",
        source,
        risk_level,
        issues,
    )
    return UserFacingGateResult(
        text=safe,
        sanitized=True,
        issues=tuple(issues),
        fallback_tier=tier,
    )
