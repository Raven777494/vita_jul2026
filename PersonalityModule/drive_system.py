# PersonalityModule/drive_system.py
# P9.1 — 抽象驅動：connection_hunger / curiosity_drive
#
# 不做：內分泌、ACE、激素衰減、ABCD。
# 做：可觀測 0–1 驅動 + 低風險議程；危機時強制壓制。
# Zero-Truncation：公開結構完整欄位，不做字串截斷。

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .version import DRIVE_SCHEMA_VERSION as DRIVE_VERSION

# 閾值：超過才寫入主動議程（避免每輪催促）
CONNECTION_AGENDA_THRESHOLD = 0.55
CURIOSITY_AGENDA_THRESHOLD = 0.50

# 時間成長（小時）
HOURS_TO_FULL_CONNECTION_HUNGER = 48.0
HOURS_TO_FULL_CURIOSITY = 72.0

# 每輪互動飽食量
CONNECTION_SATIATION_BASE = 0.18
CURIOSITY_SATIATION_BASE = 0.12


@dataclass
class DriveState:
    """抽象驅動狀態；Zero-Truncation：完整公開欄位。"""

    connection_hunger: float = 0.25
    curiosity_drive: float = 0.20
    last_interaction_ts: Optional[float] = None
    hours_since_contact: float = 0.0
    crisis_suppressed: bool = False
    active_agenda: List[str] = field(default_factory=list)
    satiation_this_turn: Dict[str, float] = field(default_factory=dict)
    version: str = DRIVE_VERSION
    source: str = "drive_system"

    def to_public_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        # 保證列表／字典完整拷貝
        payload["active_agenda"] = list(self.active_agenda)
        payload["satiation_this_turn"] = dict(self.satiation_this_turn)
        return payload


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))


def _safe_intensity(raw: Any) -> str:
    text = str(raw or "medium").strip().lower()
    if text in {"crisis", "high", "medium", "low"}:
        return text
    return "medium"


def load_drive_state(session_state: Optional[Dict[str, Any]]) -> DriveState:
    """從 session_state['drive_state'] 還原；缺欄位用預設（不截斷既有鍵）。"""
    state = DriveState()
    if not isinstance(session_state, dict):
        return state
    raw = session_state.get("drive_state")
    if not isinstance(raw, dict):
        return state

    state.connection_hunger = _clamp01(raw.get("connection_hunger"), 0.25)
    state.curiosity_drive = _clamp01(raw.get("curiosity_drive"), 0.20)
    ts = raw.get("last_interaction_ts")
    if ts is None:
        state.last_interaction_ts = None
    else:
        try:
            state.last_interaction_ts = float(ts)
        except (TypeError, ValueError):
            state.last_interaction_ts = None
    try:
        state.hours_since_contact = max(0.0, float(raw.get("hours_since_contact") or 0.0))
    except (TypeError, ValueError):
        state.hours_since_contact = 0.0
    state.crisis_suppressed = bool(raw.get("crisis_suppressed", False))
    agenda = raw.get("active_agenda")
    if isinstance(agenda, list):
        state.active_agenda = [str(x) for x in agenda if str(x).strip()]
    sat = raw.get("satiation_this_turn")
    if isinstance(sat, dict):
        state.satiation_this_turn = {
            str(k): _clamp01(v) for k, v in sat.items()
        }
    ver = raw.get("version")
    if isinstance(ver, str) and ver.strip():
        state.version = ver.strip()
    return state


def _hours_since(last_ts: Optional[float], now_ts: float) -> float:
    if last_ts is None:
        return 0.0
    try:
        delta = max(0.0, float(now_ts) - float(last_ts))
    except (TypeError, ValueError):
        return 0.0
    return delta / 3600.0


def metabolize_drives(
    *,
    prior: DriveState,
    now_ts: Optional[float] = None,
    intensity: str = "medium",
    risk_level: int = 0,
) -> DriveState:
    """
    回合開始前：按離線時長成長驅動；危機／高風險壓制。
    """
    now = float(now_ts if now_ts is not None else time.time())
    hours = _hours_since(prior.last_interaction_ts, now)
    level = _safe_intensity(intensity)
    try:
        risk = int(risk_level or 0)
    except (TypeError, ValueError):
        risk = 0

    crisis = level == "crisis" or risk >= 4
    high = level == "high" or risk >= 3

    connection = prior.connection_hunger
    curiosity = prior.curiosity_drive

    if prior.last_interaction_ts is not None and hours > 0:
        connection = _clamp01(
            connection + (hours / HOURS_TO_FULL_CONNECTION_HUNGER)
        )
        curiosity = _clamp01(
            curiosity + (hours / HOURS_TO_FULL_CURIOSITY)
        )
    elif prior.last_interaction_ts is None:
        # 新會話：輕量基線，唔急推主動
        connection = _clamp01(max(connection, 0.25))
        curiosity = _clamp01(max(curiosity, 0.20))

    agenda: List[str] = []
    suppressed = False
    if crisis or high:
        suppressed = True
        connection = min(connection, 0.15 if crisis else 0.25)
        curiosity = min(curiosity, 0.10 if crisis else 0.20)
    else:
        if connection >= CONNECTION_AGENDA_THRESHOLD:
            agenda.append("soft_connection_check_in")
        if curiosity >= CURIOSITY_AGENDA_THRESHOLD:
            agenda.append("light_curiosity_prompt")

    return DriveState(
        connection_hunger=connection,
        curiosity_drive=curiosity,
        last_interaction_ts=prior.last_interaction_ts,
        hours_since_contact=hours,
        crisis_suppressed=suppressed,
        active_agenda=agenda,
        satiation_this_turn={},
        version=DRIVE_VERSION,
        source="drive_system.metabolize",
    )


def apply_interaction_satiation(
    *,
    state: DriveState,
    user_input: str = "",
    intimacy_delta: float = 0.0,
    intensity: str = "medium",
    now_ts: Optional[float] = None,
) -> DriveState:
    """
    回合結束：互動飽食（降低 hunger／curiosity）；更新 last_interaction_ts。
    危機輪：幾乎唔改變驅動成長邏輯以外的壓制狀態，只記時間戳。
    """
    now = float(now_ts if now_ts is not None else time.time())
    level = _safe_intensity(intensity)
    text = user_input if isinstance(user_input, str) else ""
    length_factor = min(1.0, len(text) / 80.0) if text else 0.0
    intimacy_boost = _clamp01(abs(float(intimacy_delta or 0.0)) * 8.0)

    novelty_markers = (
        "第一次", "今日", "突然", "新", "發現", "好奇", "點解", "為什麼",
        "想知", "分享", "發生",
    )
    novelty = 0.15 if any(m in text for m in novelty_markers) else 0.0

    conn_sat = CONNECTION_SATIATION_BASE * (0.5 + 0.5 * length_factor) + intimacy_boost * 0.1
    cur_sat = CURIOSITY_SATIATION_BASE * (0.4 + 0.6 * length_factor) + novelty

    if level in {"crisis", "high"}:
        conn_sat *= 0.35
        cur_sat *= 0.25

    connection = _clamp01(state.connection_hunger - conn_sat)
    curiosity = _clamp01(state.curiosity_drive - cur_sat)

    # 飽食後清議程；下次 metabolize 再算
    return DriveState(
        connection_hunger=connection,
        curiosity_drive=curiosity,
        last_interaction_ts=now,
        hours_since_contact=0.0,
        crisis_suppressed=state.crisis_suppressed,
        active_agenda=[],
        satiation_this_turn={
            "connection": round(_clamp01(conn_sat), 6),
            "curiosity": round(_clamp01(cur_sat), 6),
        },
        version=DRIVE_VERSION,
        source="drive_system.satiation",
    )


def format_drive_guidance(state: DriveState) -> str:
    """
    完整驅動指引塊（Zero-Truncation：不截斷數值與議程列表）。
    危機壓制時仍輸出完整狀態，但明確禁止主動催促。
    """
    agenda = state.active_agenda if isinstance(state.active_agenda, list) else []
    agenda_line = "、".join(agenda) if agenda else "(none)"
    lines = [
        "ABSTRACT DRIVES (no endocrine / no hormones):",
        f"- connection_hunger: {state.connection_hunger:.4f}",
        f"- curiosity_drive: {state.curiosity_drive:.4f}",
        f"- hours_since_contact: {state.hours_since_contact:.4f}",
        f"- crisis_suppressed: {str(bool(state.crisis_suppressed)).lower()}",
        f"- active_agenda: {agenda_line}",
        f"- drive_version: {state.version}",
    ]
    if state.crisis_suppressed:
        lines.extend(
            [
                "DRIVE POLICY (suppressed):",
                "1. Do not initiate check-in or curiosity prompts this turn",
                "2. Presence and validation only; no agenda push",
                "3. Do not make promises while addressing drives",
            ]
        )
    elif agenda:
        lines.append("DRIVE POLICY (low-risk agenda allowed):")
        if "soft_connection_check_in" in agenda:
            lines.append(
                "1. Soft connection: at most one gentle present-tense check-in "
                "if it fits; no future promises"
            )
        if "light_curiosity_prompt" in agenda:
            lines.append(
                "2. Light curiosity: at most one short wonder about their world "
                "if low-risk; never pry in crisis tone"
            )
        lines.append(
            "3. Agenda is optional spice, never overrides safety / validation / no-promise rules"
        )
    else:
        lines.extend(
            [
                "DRIVE POLICY (idle):",
                "1. No forced agenda this turn",
                "2. Respond to the user; drives remain observable only",
            ]
        )
    return "\n".join(lines)


def resolve_drives_for_draft(
    session_state: Optional[Dict[str, Any]],
    *,
    intensity: str = "medium",
    risk_level: int = 0,
    now_ts: Optional[float] = None,
) -> Tuple[DriveState, str, Dict[str, Any]]:
    """
    Draft 前置一次解析：metabolize → guidance → public dict。
    回傳 (state, guidance_text, public_dict)；guidance 永不截斷。
    """
    prior = load_drive_state(session_state)
    state = metabolize_drives(
        prior=prior,
        now_ts=now_ts,
        intensity=intensity,
        risk_level=risk_level,
    )
    guidance = format_drive_guidance(state)
    return state, guidance, state.to_public_dict()
