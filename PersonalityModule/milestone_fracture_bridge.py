# PersonalityModule/milestone_fracture_bridge.py
# P9.2 — milestone／fracture → 人格 draft 指引
#
# 職責：正規化 orchestrator／DB 訊號，產出可觀測 bundle + 完整 prompt 塊。
# 不做：ABCD、ACE、內分泌、改 canon。
# Zero-Truncation：選取「最多 N 條」完整條目；不截斷 title／description／keyword。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .version import RELATIONAL_BRIDGE_VERSION as BRIDGE_VERSION

MAX_MILESTONES = 3
MAX_FRACTURES = 3


@dataclass
class NormalizedMilestone:
    milestone_id: str = ""
    milestone_type: str = ""
    title: str = ""
    description: str = ""
    severity: int = 0
    created_at: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "milestone_type": self.milestone_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "created_at": self.created_at,
            "meta": dict(self.meta) if isinstance(self.meta, dict) else {},
        }


@dataclass
class NormalizedFracture:
    trigger_keyword: str = ""
    context_tags: List[str] = field(default_factory=list)
    emotion_spike_score: float = 0.0
    comfort_efficiency: float = 0.5
    trigger_count: int = 0
    last_triggered: str = ""
    decay_rate: float = 0.08

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "trigger_keyword": self.trigger_keyword,
            "context_tags": list(self.context_tags),
            "emotion_spike_score": self.emotion_spike_score,
            "comfort_efficiency": self.comfort_efficiency,
            "trigger_count": self.trigger_count,
            "last_triggered": self.last_triggered,
            "decay_rate": self.decay_rate,
        }


@dataclass
class RelationalContextBundle:
    milestones: List[NormalizedMilestone] = field(default_factory=list)
    fractures: List[NormalizedFracture] = field(default_factory=list)
    milestone_count: int = 0
    fracture_count: int = 0
    intensity: str = "medium"
    version: str = BRIDGE_VERSION
    source: str = "milestone_fracture_bridge"

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "milestones": [m.to_public_dict() for m in self.milestones],
            "fractures": [f.to_public_dict() for f in self.fractures],
            "milestone_count": self.milestone_count,
            "fracture_count": self.fracture_count,
            "intensity": self.intensity,
            "version": self.version,
            "source": self.source,
        }


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_milestone(raw: Any) -> Optional[NormalizedMilestone]:
    if not isinstance(raw, dict):
        return None
    title = _safe_str(raw.get("title")).strip()
    mtype = _safe_str(raw.get("milestone_type")).strip()
    desc = _safe_str(raw.get("description")).strip()
    if not title and not mtype and not desc:
        return None
    meta = raw.get("meta")
    return NormalizedMilestone(
        milestone_id=_safe_str(raw.get("milestone_id")).strip(),
        milestone_type=mtype,
        title=title or mtype or "(milestone)",
        description=desc,
        severity=_safe_int(raw.get("severity"), 0),
        created_at=_safe_str(raw.get("created_at")).strip(),
        meta=dict(meta) if isinstance(meta, dict) else {},
    )


def _normalize_fracture(raw: Any) -> Optional[NormalizedFracture]:
    if not isinstance(raw, dict):
        return None
    keyword = _safe_str(raw.get("trigger_keyword")).strip()
    tags_raw = raw.get("context_tags")
    tags: List[str] = []
    if isinstance(tags_raw, list):
        tags = [_safe_str(t).strip() for t in tags_raw if _safe_str(t).strip()]
    elif isinstance(tags_raw, str) and tags_raw.strip():
        tags = [tags_raw.strip()]
    if not keyword and not tags:
        return None
    return NormalizedFracture(
        trigger_keyword=keyword,
        context_tags=tags,
        emotion_spike_score=_safe_float(raw.get("emotion_spike_score"), 0.0),
        comfort_efficiency=_safe_float(raw.get("comfort_efficiency"), 0.5),
        trigger_count=_safe_int(raw.get("trigger_count"), 0),
        last_triggered=_safe_str(raw.get("last_triggered")).strip(),
        decay_rate=_safe_float(raw.get("decay_rate"), 0.08),
    )


def _rank_milestones(items: List[NormalizedMilestone]) -> List[NormalizedMilestone]:
    # 嚴重度高優先；同嚴重度保留輸入順序（通常已是新→舊）
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (-pair[1].severity, pair[0]))
    return [m for _, m in indexed]


def _rank_fractures(items: List[NormalizedFracture]) -> List[NormalizedFracture]:
    indexed = list(enumerate(items))
    indexed.sort(
        key=lambda pair: (
            -pair[1].trigger_count,
            -pair[1].emotion_spike_score,
            pair[0],
        )
    )
    return [f for _, f in indexed]


def build_relational_context(
    *,
    milestones: Optional[List[Any]] = None,
    fractures: Optional[List[Any]] = None,
    intensity: str = "medium",
    max_milestones: int = MAX_MILESTONES,
    max_fractures: int = MAX_FRACTURES,
) -> RelationalContextBundle:
    """選最多 N 條完整條目（不截斷字段內容）。"""
    mil_norm: List[NormalizedMilestone] = []
    for raw in milestones or []:
        item = _normalize_milestone(raw)
        if item is not None:
            mil_norm.append(item)
    frac_norm: List[NormalizedFracture] = []
    for raw in fractures or []:
        item = _normalize_fracture(raw)
        if item is not None:
            frac_norm.append(item)

    mil_cap = max(0, min(int(max_milestones), 20))
    frac_cap = max(0, min(int(max_fractures), 20))
    selected_m = _rank_milestones(mil_norm)[:mil_cap]
    selected_f = _rank_fractures(frac_norm)[:frac_cap]
    level = str(intensity or "medium").strip().lower()
    if level not in {"crisis", "high", "medium", "low"}:
        level = "medium"

    return RelationalContextBundle(
        milestones=selected_m,
        fractures=selected_f,
        milestone_count=len(selected_m),
        fracture_count=len(selected_f),
        intensity=level,
        version=BRIDGE_VERSION,
        source="milestone_fracture_bridge",
    )


def format_relational_guidance(bundle: RelationalContextBundle) -> str:
    """
    完整關係共構指引（Zero-Truncation：每條完整寫入 title／description／tags）。
    """
    lines: List[str] = [
        "RELATIONAL CONTEXT (milestones + fractures; co-constructed history):",
        f"- bridge_version: {bundle.version}",
        f"- intensity: {bundle.intensity}",
        f"- milestone_count: {bundle.milestone_count}",
        f"- fracture_count: {bundle.fracture_count}",
    ]

    if bundle.milestones:
        lines.append("MILESTONES (shared history markers; full entries):")
        for idx, m in enumerate(bundle.milestones, start=1):
            lines.append(
                f"  [{idx}] id={m.milestone_id or '-'} type={m.milestone_type or '-'} "
                f"severity={m.severity} created_at={m.created_at or '-'}"
            )
            lines.append(f"      title: {m.title}")
            if m.description:
                lines.append(f"      description: {m.description}")
    else:
        lines.append("MILESTONES: (none this turn)")

    if bundle.fractures:
        lines.append("FRACTURES (handle gently; do not dig or dramatize):")
        for idx, f in enumerate(bundle.fractures, start=1):
            tags = "、".join(f.context_tags) if f.context_tags else "(none)"
            lines.append(
                f"  [{idx}] keyword={f.trigger_keyword or '-'} "
                f"trigger_count={f.trigger_count} "
                f"emotion_spike_score={f.emotion_spike_score:.4f} "
                f"comfort_efficiency={f.comfort_efficiency:.4f} "
                f"last_triggered={f.last_triggered or '-'}"
            )
            lines.append(f"      context_tags: {tags}")
    else:
        lines.append("FRACTURES: (none this turn)")

    lines.append("RELATIONAL POLICY:")
    if bundle.intensity in {"crisis", "high"}:
        lines.extend(
            [
                "1. If fractures present: quiet presence first; do not probe the wound",
                "2. Milestones may inform tone only; do not celebrate or lecture",
                "3. No promises; no forced agenda; validation overrides history storytelling",
            ]
        )
    else:
        lines.extend(
            [
                "1. Let shared milestones subtly color presence (we have history)",
                "2. If a fracture is active: soften pace; avoid teasing near the wound",
                "3. Do not invent details beyond listed entries; do not make promises",
                "4. Optional: one gentle acknowledgement of shared history if natural",
            ]
        )
    return "\n".join(lines)


def resolve_relational_context_for_draft(
    *,
    milestones: Optional[List[Any]] = None,
    fractures: Optional[List[Any]] = None,
    intensity: str = "medium",
) -> Tuple[RelationalContextBundle, str, Dict[str, Any]]:
    bundle = build_relational_context(
        milestones=milestones,
        fractures=fractures,
        intensity=intensity,
    )
    guidance = format_relational_guidance(bundle)
    return bundle, guidance, bundle.to_public_dict()
