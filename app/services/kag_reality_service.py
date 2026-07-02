"""KAG Reality Layer — verifiable fact grounding for v9 generation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.kag_fact_extractor import extract_user_facts

logger = logging.getLogger(__name__)

HK_TZ = timezone(timedelta(hours=8))
_SEED_PATH = Path(__file__).resolve().parents[2] / "config" / "reality_seed.json"


@dataclass
class RealityLayerResult:
    """Output of a single KAG Reality Layer pass."""

    context_text: str = ""
    facts: List[Dict[str, Any]] = field(default_factory=list)
    degraded: bool = False
    sources: List[str] = field(default_factory=list)


class KAGRealityService:
    """
    Knowledge-Augmented Generation — Reality Layer.

    Separates verifiable facts (time, persona, safety, user-stated facts)
    from emotional memory retrieval. Injected into v9 context as grounding.
    """

    def __init__(
        self,
        db_manager: Any,
        *,
        hko_service: Any = None,
        enabled: bool = True,
        max_facts: int = 12,
        persona_name: str = "希兒",
    ) -> None:
        self.db = db_manager
        self.hko = hko_service
        self.enabled = bool(enabled)
        self.max_facts = max(4, min(max_facts, 30))
        self.persona_name = persona_name
        self._seeds_loaded = False

    def ensure_seed_facts(self) -> int:
        """Load global seed facts from config/reality_seed.json (idempotent)."""
        if not self.enabled or not self.db or self._seeds_loaded:
            return 0

        if not _SEED_PATH.exists():
            logger.warning("[KAG] reality_seed.json not found at %s", _SEED_PATH)
            self._seeds_loaded = True
            return 0

        try:
            with open(_SEED_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[KAG] failed to load seed file: %s", exc)
            self._seeds_loaded = True
            return 0

        count = 0
        for item in payload.get("facts") or []:
            fid = self.db.upsert_reality_fact(
                subject=str(item.get("subject", "system")),
                predicate=str(item.get("predicate", "fact")),
                object_value=str(item.get("object_value", "")),
                user_id=None,
                confidence=float(item.get("confidence", 1.0)),
                source=str(item.get("source", "system_seed")),
                is_seed=True,
            )
            if fid is not None:
                count += 1

        persona_fact = (
            f"Seele（{self.persona_name}）是 Vita 系統 AI 心理伴侶，"
            f"以繁體中文／粵語與用戶對話。"
        )
        self.db.upsert_reality_fact(
            subject="seele",
            predicate="display_name",
            object_value=persona_fact,
            user_id=None,
            confidence=1.0,
            source="system_seed",
            is_seed=True,
        )
        self._seeds_loaded = True
        logger.info("[KAG] seed facts ensured count=%s", count + 1)
        return count + 1

    def _dynamic_world_facts(self, weather_context: str = "") -> List[Dict[str, Any]]:
        now = datetime.now(HK_TZ)
        facts: List[Dict[str, Any]] = [
            {
                "subject": "world",
                "predicate": "current_datetime_hk",
                "object_value": now.strftime("%Y-%m-%d %H:%M %A (Asia/Hong_Kong)"),
                "confidence": 1.0,
                "source": "system_clock",
            },
            {
                "subject": "world",
                "predicate": "weekday_hk",
                "object_value": now.strftime("%A"),
                "confidence": 1.0,
                "source": "system_clock",
            },
        ]
        if weather_context:
            snippet = weather_context.strip()[:400]
            facts.append({
                "subject": "world",
                "predicate": "weather_context",
                "object_value": snippet,
                "confidence": 0.95,
                "source": "hko",
            })
        return facts

    def _shadow_facts(self, shadow_dict: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not shadow_dict:
            return []
        return [
            {
                "subject": "user_shadow",
                "predicate": "pain",
                "object_value": f"{float(shadow_dict.get('pain', 0)):.2f}",
                "confidence": 0.9,
                "source": "user_shadow",
            },
            {
                "subject": "user_shadow",
                "predicate": "trust",
                "object_value": f"{float(shadow_dict.get('trust', 0.5)):.2f}",
                "confidence": 0.9,
                "source": "user_shadow",
            },
            {
                "subject": "user_shadow",
                "predicate": "hope",
                "object_value": f"{float(shadow_dict.get('hope', 0.5)):.2f}",
                "confidence": 0.9,
                "source": "user_shadow",
            },
            {
                "subject": "user_shadow",
                "predicate": "loneliness",
                "object_value": f"{float(shadow_dict.get('loneliness', 0)):.2f}",
                "confidence": 0.9,
                "source": "user_shadow",
            },
        ]

    def _milestone_facts(
        self,
        milestones: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        if not milestones:
            return []
        facts: List[Dict[str, Any]] = []
        for m in milestones[:3]:
            facts.append({
                "subject": "relationship",
                "predicate": str(m.get("milestone_type", "milestone")),
                "object_value": str(m.get("title", "")),
                "confidence": 0.85,
                "source": "psychological_milestone",
            })
        return facts

    def build_reality_layer(
        self,
        *,
        user_id: str,
        user_text: str,
        risk_level: int = 0,
        weather_context: str = "",
        shadow_dict: Optional[Dict[str, Any]] = None,
        milestones: Optional[List[Dict[str, Any]]] = None,
    ) -> RealityLayerResult:
        """Synchronous build — call via run_in_executor from async code."""
        if not self.enabled or not self.db:
            return RealityLayerResult(degraded=True, sources=["disabled"])

        try:
            self.ensure_seed_facts()

            stored = self.db.search_reality_facts(
                user_id,
                user_text,
                limit=self.max_facts,
            )

            facts: List[Dict[str, Any]] = []
            seen: set = set()

            def _add(f: Dict[str, Any]) -> None:
                key = (f.get("subject"), f.get("predicate"), f.get("object_value"))
                if key in seen:
                    return
                seen.add(key)
                facts.append(f)

            for f in stored:
                _add(f)
            for f in self._dynamic_world_facts(weather_context):
                _add(f)
            for f in self._shadow_facts(shadow_dict):
                _add(f)
            for f in self._milestone_facts(milestones):
                _add(f)

            if risk_level >= 3:
                _add({
                    "subject": "safety",
                    "predicate": "elevated_risk",
                    "object_value": (
                        f"session_risk_level={risk_level}; "
                        "prioritize companion empathy, grounding, and presence; "
                        "do not provide hotlines, ER, hospitalization, or medication directives"
                    ),
                    "confidence": 1.0,
                    "source": "risk_assessment",
                })

            facts = facts[: self.max_facts]
            context = self._format_context(facts)
            sources = sorted({str(f.get("source", "unknown")) for f in facts})

            return RealityLayerResult(
                context_text=context,
                facts=facts,
                degraded=len(facts) == 0,
                sources=sources or ["empty"],
            )
        except Exception as exc:
            logger.warning("[KAG] build_reality_layer failed: %s", exc)
            return RealityLayerResult(degraded=True, sources=["error"])

    def persist_user_statement_facts(
        self,
        *,
        user_id: str,
        user_text: str,
        session_id: Optional[str] = None,
    ) -> List[int]:
        """Extract and persist user-stated facts from utterance."""
        if not self.enabled or not self.db:
            return []

        ids: List[int] = []
        for fact in extract_user_facts(user_text):
            fid = self.db.upsert_reality_fact(
                subject=fact["subject"],
                predicate=fact["predicate"],
                object_value=fact["object_value"],
                user_id=user_id,
                confidence=float(fact.get("confidence", 0.7)),
                source=fact.get("source", "user_statement"),
                session_id=session_id,
            )
            if fid is not None:
                ids.append(fid)
        return ids

    @staticmethod
    def _format_context(facts: List[Dict[str, Any]]) -> str:
        if not facts:
            return ""

        lines = [
            "=== KAG Reality Layer (verified facts — do not contradict) ===",
            "Use only these anchors for factual claims; emotional memory is separate.",
        ]
        for f in facts:
            subj = f.get("subject", "?")
            pred = f.get("predicate", "?")
            obj = f.get("object_value", "")
            conf = f.get("confidence")
            if conf is not None:
                lines.append(f"- [{subj}] {pred}: {obj} (confidence={float(conf):.2f})")
            else:
                lines.append(f"- [{subj}] {pred}: {obj}")
        return "\n".join(lines)
