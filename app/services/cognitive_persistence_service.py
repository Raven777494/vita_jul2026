"""Phase 5: User Shadow PostgreSQL persistence and psychological milestones."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.user_shadow_service import (
    UserShadow,
    build_user_shadow,
)

logger = logging.getLogger(__name__)

MILESTONE_TURN_COUNTS = (10, 50, 100, 250)


class CognitivePersistenceService:
    """Load, evolve, and persist User Shadow + relationship milestones."""

    def __init__(self, db_manager: Any, *, enabled: bool = True) -> None:
        self.db = db_manager
        self.enabled = bool(enabled)

    def load_shadow_dict(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled or not self.db:
            return None
        try:
            return self.db.get_user_shadow_state(user_id)
        except Exception as exc:
            logger.warning("[COGNITIVE] load_shadow failed user=%s: %s", user_id, exc)
            return None

    def load_shadow(self, user_id: str) -> UserShadow:
        stored = self.load_shadow_dict(user_id)
        if stored:
            return UserShadow.from_dict(stored)
        return UserShadow()

    def detect_milestones(
        self,
        *,
        user_id: str,
        prior: UserShadow,
        evolved: UserShadow,
        emotion_profile: Dict[str, Any],
        risk_level: int,
        user_text: str,
        meta_layer: Optional[Dict[str, Any]] = None,
        prior_turn_count: int = 0,
    ) -> List[Dict[str, Any]]:
        milestones: List[Dict[str, Any]] = []
        meta_layer = meta_layer or {}

        if risk_level >= 4 or emotion_profile.get("is_crisis_risk"):
            milestones.append({
                "milestone_type": "crisis_signal",
                "title": "危機信號偵測",
                "description": "本輪對話觸發高風險或危機關鍵詞評估。",
                "severity": 5,
                "meta": {
                    "risk_level": risk_level,
                    "crisis_keywords": emotion_profile.get("detected_crisis_keywords", []),
                },
            })

        if evolved.trust - prior.trust >= 0.15:
            milestones.append({
                "milestone_type": "trust_breakthrough",
                "title": "信任提升",
                "description": "使用者在本輪對話中展現明顯信任提升。",
                "severity": 2,
                "meta": {"prior_trust": prior.trust, "evolved_trust": evolved.trust},
            })

        if prior.hope < 0.35 and evolved.hope - prior.hope >= 0.12:
            milestones.append({
                "milestone_type": "hope_restored",
                "title": "希望回升",
                "description": "從低希望狀態出現可觀察的回升。",
                "severity": 2,
                "meta": {"prior_hope": prior.hope, "evolved_hope": evolved.hope},
            })

        if evolved.loneliness >= 0.75:
            milestones.append({
                "milestone_type": "deep_loneliness",
                "title": "深度孤獨感",
                "description": "User Shadow 孤獨指標達到高閾值。",
                "severity": 3,
                "meta": {"loneliness": evolved.loneliness},
            })

        if evolved.trust >= 0.7 and prior.trust < 0.7:
            milestones.append({
                "milestone_type": "relationship_bond",
                "title": "關係連結建立",
                "description": "信任指標跨越穩定關係閾值。",
                "severity": 2,
                "meta": {"trust": evolved.trust},
            })

        new_turn_count = prior_turn_count + 1
        for threshold in MILESTONE_TURN_COUNTS:
            if prior_turn_count < threshold <= new_turn_count:
                milestones.append({
                    "milestone_type": f"turn_milestone_{threshold}",
                    "title": f"對話里程碑 {threshold} 輪",
                    "description": f"使用者累積對話達 {threshold} 輪。",
                    "severity": 1,
                    "meta": {"turn_count": new_turn_count},
                })

        critic = float(meta_layer.get("critic_score", 1.0) or 1.0)
        if meta_layer.get("audit_ran") and critic < 0.5:
            milestones.append({
                "milestone_type": "quality_concern",
                "title": "回應品質需關注",
                "description": "Meta Auditor 評分偏低，已記錄品質關注點。",
                "severity": 2,
                "meta": {"critic_score": critic},
            })

        pain_keywords = ("痛", "難受", "崩潰", "孤單", "害怕", "絕望")
        if any(kw in (user_text or "") for kw in pain_keywords) and evolved.pain > prior.pain:
            milestones.append({
                "milestone_type": "emotional_disclosure",
                "title": "情緒揭露",
                "description": "使用者在本輪表達明顯痛苦或脆弱感受。",
                "severity": 2,
                "meta": {"pain": evolved.pain},
            })

        return milestones

    def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        emotion_profile: Dict[str, Any],
        risk_level: int,
        session_state: Dict[str, Any],
        meta_layer: Optional[Dict[str, Any]] = None,
        user_text: str = "",
        evolved_shadow: Optional[Dict[str, float]] = None,
    ) -> Tuple[UserShadow, List[int]]:
        """
        Evolve shadow from stored state + current turn, persist, record milestones.
        Returns (evolved_shadow, milestone_ids).
        """
        if not self.enabled or not self.db:
            instant = build_user_shadow(
                session_state=session_state,
                emotion_profile=emotion_profile,
                risk_level=risk_level,
            )
            return instant, []

        stored_row = self.load_shadow_dict(user_id) or {}
        prior = UserShadow.from_dict(stored_row) if stored_row else UserShadow()
        prior_turn_count = int(stored_row.get("turn_count", 0) or 0)

        if evolved_shadow:
            evolved = UserShadow.from_dict(evolved_shadow)
        else:
            instant = build_user_shadow(
                session_state=session_state,
                emotion_profile=emotion_profile,
                risk_level=risk_level,
                stored_shadow=prior if stored_row else None,
            )
            evolved = instant

        emotion_snapshot = {
            "valence": emotion_profile.get("valence"),
            "arousal": emotion_profile.get("arousal"),
            "dominance": emotion_profile.get("dominance"),
            "dominant_emotion": emotion_profile.get("dominant_emotion"),
            "emotion_dimensions": emotion_profile.get("emotion_dimensions"),
        }

        self.db.upsert_user_shadow_state(
            user_id,
            evolved.to_dict(),
            session_id=session_id,
            emotion_snapshot=emotion_snapshot,
        )

        milestone_ids: List[int] = []
        for item in self.detect_milestones(
            user_id=user_id,
            prior=prior,
            evolved=evolved,
            emotion_profile=emotion_profile,
            risk_level=risk_level,
            user_text=user_text,
            meta_layer=meta_layer,
            prior_turn_count=prior_turn_count,
        ):
            mid = self.db.insert_psychological_milestone(
                user_id=user_id,
                milestone_type=item["milestone_type"],
                title=item["title"],
                description=item.get("description", ""),
                session_id=session_id,
                severity=int(item.get("severity", 1)),
                meta=item.get("meta") or {},
            )
            if mid is not None:
                milestone_ids.append(mid)

        return evolved, milestone_ids
