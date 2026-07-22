# PersonalityModule/disposition_system.py
# P9.3 — Nightly disposition（穩定偏好鞏固）
#
# 職責：離線把可觀察訊號鞏固成跨日偏好基線，供 draft 讀取。
# 不做：內分泌、ACE、ABCD、道德審判、激素睡眠。
# Zero-Truncation：完整公開欄位；evidence 只限條數，不截斷單條文案。

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .version import DISPOSITION_SCHEMA_VERSION as DISPOSITION_VERSION
REDIS_KEY_PREFIX = "persona_disposition:"
MAX_EVIDENCE = 8
MAX_LABELS = 12
EMA_PRIOR_WEIGHT = 0.40
EMA_NEW_WEIGHT = 0.60


@dataclass
class DispositionState:
    """跨日穩定偏好（非激素、非道德量表）。"""

    prefer_presence_over_advice: float = 0.75
    prefer_soft_humor: float = 0.35
    prefer_quiet_pace: float = 0.40
    fracture_softness: float = 0.50
    connection_baseline: float = 0.25
    curiosity_baseline: float = 0.20
    intimacy_anchor: float = 0.50
    preference_labels: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    consolidated_at: str = ""
    source: str = "disposition_system"
    version: str = DISPOSITION_VERSION

    def to_public_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["preference_labels"] = list(self.preference_labels)
        payload["evidence"] = list(self.evidence)
        return payload


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redis_key_for_user(user_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}{_safe_str(user_id).strip() or 'unknown'}"


def load_disposition(session_state: Optional[Dict[str, Any]]) -> DispositionState:
    if not isinstance(session_state, dict):
        return DispositionState()
    raw = session_state.get("disposition")
    if not isinstance(raw, dict):
        raw = session_state.get("persona_disposition")
    if not isinstance(raw, dict):
        return DispositionState()
    return disposition_from_dict(raw)


def disposition_from_dict(raw: Dict[str, Any]) -> DispositionState:
    labels_raw = raw.get("preference_labels")
    evidence_raw = raw.get("evidence")
    labels: List[str] = []
    evidence: List[str] = []
    if isinstance(labels_raw, list):
        labels = [_safe_str(x).strip() for x in labels_raw if _safe_str(x).strip()]
    if isinstance(evidence_raw, list):
        evidence = [_safe_str(x).strip() for x in evidence_raw if _safe_str(x).strip()]
    return DispositionState(
        prefer_presence_over_advice=_clamp01(
            raw.get("prefer_presence_over_advice"), 0.75
        ),
        prefer_soft_humor=_clamp01(raw.get("prefer_soft_humor"), 0.35),
        prefer_quiet_pace=_clamp01(raw.get("prefer_quiet_pace"), 0.40),
        fracture_softness=_clamp01(raw.get("fracture_softness"), 0.50),
        connection_baseline=_clamp01(raw.get("connection_baseline"), 0.25),
        curiosity_baseline=_clamp01(raw.get("curiosity_baseline"), 0.20),
        intimacy_anchor=_clamp01(raw.get("intimacy_anchor"), 0.50),
        preference_labels=labels[:MAX_LABELS],
        evidence=evidence[:MAX_EVIDENCE],
        consolidated_at=_safe_str(raw.get("consolidated_at")).strip(),
        source=_safe_str(raw.get("source")).strip() or "disposition_system",
        version=_safe_str(raw.get("version")).strip() or DISPOSITION_VERSION,
    )


def _ema(prior: float, new: float) -> float:
    return _clamp01(EMA_PRIOR_WEIGHT * prior + EMA_NEW_WEIGHT * new)


def _merge_labels(prior: List[str], new: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in list(new) + list(prior):
        text = _safe_str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= MAX_LABELS:
            break
    return out


def _merge_evidence(prior: List[str], new: List[str]) -> List[str]:
    # 新證據優先；完整保留每條（不截斷），只限條數
    out: List[str] = []
    seen = set()
    for item in list(new) + list(prior):
        text = _safe_str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= MAX_EVIDENCE:
            break
    return out


def consolidate_disposition(
    *,
    prior: Optional[DispositionState] = None,
    intimacy: float = 0.5,
    daily_health_score: float = 50.0,
    glimmers_daily: int = 0,
    trauma_bond_risk: float = 0.0,
    connection_hunger: Optional[float] = None,
    curiosity_drive: Optional[float] = None,
    fracture_count: int = 0,
    crisis_days_signal: bool = False,
    source: str = "nightly",
) -> DispositionState:
    """
    由 Nightly／離線訊號鞏固偏好基線。
    偏好語意：陪伴姿態，非用戶病理標籤。
    """
    base = prior if isinstance(prior, DispositionState) else DispositionState()
    try:
        health = float(daily_health_score)
    except (TypeError, ValueError):
        health = 50.0
    try:
        glimmers = max(0, int(glimmers_daily))
    except (TypeError, ValueError):
        glimmers = 0
    trauma = _clamp01(trauma_bond_risk, 0.0)
    frac_n = max(0, int(fracture_count or 0))

    # 目標值（單日快照）
    presence = 0.70
    soft_humor = 0.30
    quiet = 0.35
    soft_fracture = 0.45
    evidence: List[str] = []
    labels: List[str] = ["presence_first"]

    if health < 40.0 or crisis_days_signal:
        presence = 0.90
        soft_humor = 0.10
        quiet = 0.80
        soft_fracture = 0.85
        labels.extend(["quiet_pace", "low_humor_window"])
        evidence.append(
            f"daily_health_score={health:.4f}; prefer quiet presence"
        )
    elif health > 60.0 and glimmers > 0:
        soft_humor = min(0.65, 0.35 + 0.08 * min(glimmers, 4))
        quiet = 0.25
        labels.extend(["soft_humor_ok", "light_warmth"])
        evidence.append(
            f"glimmers_daily={glimmers}; daily_health_score={health:.4f}; "
            "soft humor allowed in low-risk"
        )
    else:
        evidence.append(f"daily_health_score={health:.4f}; balanced pace")

    if trauma >= 0.55 or frac_n > 0:
        soft_fracture = max(soft_fracture, 0.70 + 0.05 * min(frac_n, 3))
        soft_humor = min(soft_humor, 0.25)
        quiet = max(quiet, 0.55)
        labels.append("fracture_softness")
        evidence.append(
            f"trauma_bond_risk={trauma:.4f}; fracture_count={frac_n}; "
            "soften near wounds"
        )

    presence = max(presence, 0.65)
    labels.append("no_promise_stance")

    conn_base = (
        _clamp01(connection_hunger, base.connection_baseline)
        if connection_hunger is not None
        else base.connection_baseline
    )
    cur_base = (
        _clamp01(curiosity_drive, base.curiosity_baseline)
        if curiosity_drive is not None
        else base.curiosity_baseline
    )

    merged = DispositionState(
        prefer_presence_over_advice=_ema(base.prefer_presence_over_advice, presence),
        prefer_soft_humor=_ema(base.prefer_soft_humor, soft_humor),
        prefer_quiet_pace=_ema(base.prefer_quiet_pace, quiet),
        fracture_softness=_ema(base.fracture_softness, soft_fracture),
        connection_baseline=_ema(base.connection_baseline, conn_base),
        curiosity_baseline=_ema(base.curiosity_baseline, cur_base),
        intimacy_anchor=_ema(base.intimacy_anchor, _clamp01(intimacy, 0.5)),
        preference_labels=_merge_labels(base.preference_labels, labels),
        evidence=_merge_evidence(base.evidence, evidence),
        consolidated_at=_now_iso(),
        source=source,
        version=DISPOSITION_VERSION,
    )
    return merged


def consolidate_from_nightly_assessment(
    assessment: Optional[Dict[str, Any]],
    *,
    prior: Optional[DispositionState] = None,
    prior_dict: Optional[Dict[str, Any]] = None,
) -> DispositionState:
    """NightlyJudgment 用：由 assessment dict 鞏固 disposition。"""
    data = assessment if isinstance(assessment, dict) else {}
    base = prior
    if base is None and isinstance(prior_dict, dict):
        base = disposition_from_dict(prior_dict)

    glimmers = 0
    pg = data.get("positive_glimmers_data")
    if isinstance(pg, dict):
        try:
            glimmers = int(pg.get("daily", 0) or 0)
        except (TypeError, ValueError):
            glimmers = 0

    try:
        health = float(data.get("daily_health_score") or 50.0)
    except (TypeError, ValueError):
        health = 50.0

    return consolidate_disposition(
        prior=base,
        intimacy=_clamp01(data.get("new_intimacy"), 0.5),
        daily_health_score=health,
        glimmers_daily=glimmers,
        trauma_bond_risk=_clamp01(data.get("trauma_bond_risk"), 0.0),
        connection_hunger=None,
        curiosity_drive=None,
        fracture_count=0,
        crisis_days_signal=health < 35.0,
        source="nightly",
    )


def format_disposition_guidance(state: DispositionState) -> str:
    labels = "、".join(state.preference_labels) if state.preference_labels else "(none)"
    lines = [
        "DISPOSITION BASELINE (nightly-consolidated preferences; not hormones):",
        f"- disposition_version: {state.version}",
        f"- source: {state.source}",
        f"- consolidated_at: {state.consolidated_at or '-'}",
        f"- prefer_presence_over_advice: {state.prefer_presence_over_advice:.4f}",
        f"- prefer_soft_humor: {state.prefer_soft_humor:.4f}",
        f"- prefer_quiet_pace: {state.prefer_quiet_pace:.4f}",
        f"- fracture_softness: {state.fracture_softness:.4f}",
        f"- connection_baseline: {state.connection_baseline:.4f}",
        f"- curiosity_baseline: {state.curiosity_baseline:.4f}",
        f"- intimacy_anchor: {state.intimacy_anchor:.4f}",
        f"- preference_labels: {labels}",
    ]
    if state.evidence:
        lines.append("EVIDENCE (full entries; count-capped):")
        for idx, item in enumerate(state.evidence, start=1):
            lines.append(f"  [{idx}] {item}")
    else:
        lines.append("EVIDENCE: (none)")

    lines.append("DISPOSITION POLICY:")
    lines.append(
        "1. Treat scores as stable stance hints across days, not per-turn dials"
    )
    if state.prefer_quiet_pace >= 0.60:
        lines.append(
            "2. Prefer quieter, shorter presence; reduce playful energy"
        )
    elif state.prefer_soft_humor >= 0.45:
        lines.append(
            "2. Low-risk soft humor is allowed; safety and validation still win"
        )
    else:
        lines.append("2. Keep balanced warmth; do not force jokes")
    if state.fracture_softness >= 0.60:
        lines.append(
            "3. Near known wounds: soften pace; no teasing; no digging"
        )
    lines.append(
        "4. Presence over advice; do not make promises; no ABCD labeling"
    )
    return "\n".join(lines)


def resolve_disposition_for_draft(
    session_state: Optional[Dict[str, Any]],
    *,
    turn_info: Optional[Dict[str, Any]] = None,
) -> Tuple[DispositionState, str, Dict[str, Any]]:
    info = turn_info if isinstance(turn_info, dict) else {}
    raw = info.get("disposition")
    if isinstance(raw, dict):
        state = disposition_from_dict(raw)
    else:
        state = load_disposition(session_state)
    guidance = format_disposition_guidance(state)
    return state, guidance, state.to_public_dict()


def apply_disposition_to_drive_baselines(
    disposition: DispositionState,
    drive_public: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    可選：把 nightly baseline 寫回 drive_state 觀測（不取代本輪 metabolize 結果，
    只補充 baseline 欄位；完整保留既有鍵）。
    """
    out = dict(drive_public) if isinstance(drive_public, dict) else {}
    out["connection_baseline"] = disposition.connection_baseline
    out["curiosity_baseline"] = disposition.curiosity_baseline
    out["disposition_version"] = disposition.version
    return out
