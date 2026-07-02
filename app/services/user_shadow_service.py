"""User Shadow — psychological state (Phase 5 PostgreSQL persistence)."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass
class UserShadow:
    """User psychological shadow (0.0–1.0 scales)."""

    pain: float = 0.0
    trust: float = 0.5
    hope: float = 0.5
    loneliness: float = 0.0

    def clamp(self) -> "UserShadow":
        for field in ("pain", "trust", "hope", "loneliness"):
            val = max(0.0, min(1.0, float(getattr(self, field))))
            object.__setattr__(self, field, val)
        return self

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "UserShadow":
        data = data or {}
        return cls(
            pain=float(data.get("pain", 0.0)),
            trust=float(data.get("trust", 0.5)),
            hope=float(data.get("hope", 0.5)),
            loneliness=float(data.get("loneliness", 0.0)),
        ).clamp()


def evolve_user_shadow(
    stored: UserShadow,
    instant: UserShadow,
    *,
    blend: float = 0.35,
) -> UserShadow:
    """Merge persisted shadow with turn-instant estimate (EMA-style blend)."""
    blend = max(0.0, min(1.0, float(blend)))
    keep = 1.0 - blend
    return UserShadow(
        pain=round(stored.pain * keep + instant.pain * blend, 3),
        trust=round(stored.trust * keep + instant.trust * blend, 3),
        hope=round(stored.hope * keep + instant.hope * blend, 3),
        loneliness=round(stored.loneliness * keep + instant.loneliness * blend, 3),
    ).clamp()


def build_user_shadow(
    *,
    session_state: Optional[Dict[str, Any]] = None,
    emotion_profile: Optional[Dict[str, Any]] = None,
    risk_level: int = 0,
    stored_shadow: Optional[UserShadow] = None,
    blend: float = 0.35,
) -> UserShadow:
    """Derive shadow from Phase 1 sensing; merge with persisted state when provided."""
    session_state = session_state or {}
    emotion_profile = emotion_profile or {}

    valence = float(emotion_profile.get("valence", 0.5))
    arousal = float(emotion_profile.get("arousal", 0.3))
    dominance = float(emotion_profile.get("dominance", 0.5))

    pain = min(1.0, max(0.0, (1.0 - valence) * 0.6 + arousal * 0.4))
    if risk_level >= 4:
        pain = min(1.0, pain + 0.25)
    elif risk_level >= 3:
        pain = min(1.0, pain + 0.12)

    trust = float(session_state.get("intimacy", session_state.get("trust", 0.5)))
    hope = float(session_state.get("hope", 0.5))
    if valence > 0.3:
        hope = min(1.0, hope + 0.05)
    loneliness = min(1.0, max(0.0, (1.0 - dominance) * 0.5 + (1.0 - trust) * 0.3))

    dominant = str(emotion_profile.get("dominant_emotion", "")).lower()
    if dominant in ("sadness", "lonely", "grief", "孤獨", "傷心", "sad"):
        loneliness = min(1.0, loneliness + 0.15)

    dims = emotion_profile.get("emotion_dimensions") or {}
    if isinstance(dims, dict):
        loneliness = min(1.0, loneliness + float(dims.get("loneliness", 0.0)) * 0.1)
        pain = min(1.0, pain + float(dims.get("despair", 0.0)) * 0.08)

    instant = UserShadow(
        pain=round(pain, 3),
        trust=round(trust, 3),
        hope=round(hope, 3),
        loneliness=round(loneliness, 3),
    ).clamp()

    if stored_shadow is not None:
        return evolve_user_shadow(stored_shadow, instant, blend=blend)
    return instant


def format_shadow_context(shadow: UserShadow) -> str:
    return (
        f"User Shadow: pain={shadow.pain:.2f}, trust={shadow.trust:.2f}, "
        f"hope={shadow.hope:.2f}, loneliness={shadow.loneliness:.2f}"
    )
