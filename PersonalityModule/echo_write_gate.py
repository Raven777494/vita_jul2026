# PersonalityModule/echo_write_gate.py
# P7 — Echo 寫入閘（Consolidation 衛生）

"""
讀側已有 MemoryRetrievalAPI（P6.3）；本模組統一寫側決策與可觀測 trace。

職責：
1. 回合級：何時禁止永迴軌沉澱（hint／critical drift／crisis 自傳）
2. 落盤前：空內容、非法 id、正史前綴、canon source、policy+自傳
3. 落盤後：回傳 id 再驗一次（防呆）

Zero-Truncation：只記錄 response_chars／user_input_chars，不硬截斷正文。
不做 ABCD；不做 ACE；永不允許 echo 改寫童年正史。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

ECHO_WRITE_GATE_VERSION = "1.0.0"

# 與 PersonalityModule.IMMUTABLE_SOUL_ID_PREFIXES 對齊
IMMUTABLE_SOUL_ID_PREFIXES: Tuple[str, ...] = (
    "memory_",
    "core_",
    "gold_hk_",
    "canon_",
)

CANON_SOURCE_TOKENS = frozenset(
    {
        "seele_childhood_canon",
        "canonical",
        "canon",
        "core_memories",
        "core",
    }
)

AUTOBIOGRAPHY_MARKERS: Tuple[str, ...] = (
    "我爸爸",
    "我媽媽",
    "我出世",
    "我細個",
    "我童年",
    "我以前住",
    "我家人",
    "我讀幼稚園",
    "我讀小學",
    "我讀中學",
)

# 標準 deny_reason（可觀測契約）
DENY_EMPTY_CONTENT = "empty_content"
DENY_ORCHESTRATOR_HINT = "orchestrator_hint_skip"
DENY_CRITICAL_DRIFT = "critical_narrative_drift"
DENY_CRISIS_AUTOBIOGRAPHY = "crisis_autobiography_response"
DENY_RISK_LEVEL = "risk_level_block"
DENY_JUDGE_FALSE = "judge_should_store_false"
DENY_IMMUTABLE_ID = "immutable_soul_id_collision"
DENY_ILLEGAL_ECHO_ID = "illegal_echo_id_prefix"
DENY_CANON_SOURCE = "canon_source_forbidden"
DENY_POLICY_CRITICAL_AUTOBIO = "policy_critical_autobiography"
DENY_INVALID_ECHO_SCORE = "invalid_echo_score"
DENY_STORE_FAILED = "store_failed"
ALLOW_REASON = ""


@dataclass
class EchoWriteDecision:
    allowed: bool
    deny_reason: str = ALLOW_REASON
    policy_level: str = "normal"
    stage: str = "pre_turn"
    response_chars: int = 0
    user_input_chars: int = 0
    echo_id: str = ""
    echo_score: float = 0.0
    risk_level: int = 0
    notes: List[str] = field(default_factory=list)
    version: str = ECHO_WRITE_GATE_VERSION

    def to_public_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def as_skip_tuple(self) -> Tuple[bool, str]:
        """相容舊 API： (should_skip, reason)。"""
        if self.allowed:
            return False, ""
        return True, self.deny_reason or "denied"


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_immutable_soul_memory_id(memory_id: Any) -> bool:
    mid = _safe_str(memory_id).strip()
    if not mid:
        return False
    return any(mid.startswith(prefix) for prefix in IMMUTABLE_SOUL_ID_PREFIXES)


def contains_autobiography_marker(text: str) -> bool:
    body = text or ""
    return any(marker in body for marker in AUTOBIOGRAPHY_MARKERS)


def sentiment_affect_intensity(user_sentiment: Any) -> float:
    """
    統一情感強度（修復：EmotionService 常用 valence/arousal，未必有 intensity）。
    回傳 [0, 1]。
    """
    if not isinstance(user_sentiment, dict):
        return 0.0
    if user_sentiment.get("intensity") is not None:
        return max(0.0, min(1.0, abs(_safe_float(user_sentiment.get("intensity"), 0.0))))
    arousal = _safe_float(user_sentiment.get("arousal"), 0.0)
    valence = _safe_float(user_sentiment.get("valence"), 0.0)
    # arousal 為主；valence 幅度為輔（signed VAD）
    return max(0.0, min(1.0, abs(arousal) * 0.7 + abs(valence) * 0.3))


def resolve_policy_level(
    extracted_info: Optional[Dict[str, Any]] = None,
    session_state: Optional[Dict[str, Any]] = None,
    turn_info: Optional[Dict[str, Any]] = None,
) -> str:
    info = extracted_info if isinstance(extracted_info, dict) else {}
    turn = turn_info if isinstance(turn_info, dict) else {}
    state = session_state if isinstance(session_state, dict) else {}
    for source in (info, turn, state):
        level = _safe_str(source.get("memory_policy_level")).lower()
        if level in {"normal", "strict", "critical"}:
            return level
        meta = source.get("metacognitive_control")
        if isinstance(meta, dict):
            alert = _safe_str(meta.get("drift_alert_level")).lower()
            if alert == "critical":
                return "critical"
            if alert == "warning":
                return "strict"
        alert = _safe_str(
            source.get("narrative_drift_alert_level") or source.get("alert_level")
        ).lower()
        if alert == "critical":
            return "critical"
        if alert == "warning":
            return "strict"
    return "normal"


def _extract_hooks(
    turn_info: Optional[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]],
    extracted_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """輕量讀取 skip hint（不依賴 PersonalityModule，避免循環 import）。"""
    hooks: Dict[str, Any] = {}
    for source in (extracted_info, turn_info, session_state):
        if not isinstance(source, dict):
            continue
        nested = source.get("orchestrator_hints")
        if isinstance(nested, dict) and nested.get("skip_echo_consolidation") is not None:
            hooks["skip_echo_consolidation"] = bool(nested.get("skip_echo_consolidation"))
        if source.get("skip_echo_consolidation") is not None:
            hooks["skip_echo_consolidation"] = bool(source.get("skip_echo_consolidation"))
    return hooks


def _resolve_intensity(
    turn_info: Optional[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]],
    extracted_info: Optional[Dict[str, Any]] = None,
) -> str:
    for source in (extracted_info, turn_info, session_state):
        if not isinstance(source, dict):
            continue
        pre = source.get("pre_draft_guidance")
        if isinstance(pre, dict) and pre.get("intensity"):
            return _safe_str(pre.get("intensity")).lower()
        if source.get("intensity"):
            return _safe_str(source.get("intensity")).lower()
    return ""


def _resolve_drift_alert(
    drift_info: Optional[Dict[str, Any]],
    turn_info: Optional[Dict[str, Any]],
    extracted_info: Optional[Dict[str, Any]] = None,
) -> str:
    for source in (drift_info, extracted_info, turn_info):
        if not isinstance(source, dict):
            continue
        alert = _safe_str(
            source.get("alert_level")
            or source.get("narrative_drift_alert_level")
        ).lower()
        if alert:
            return alert
    return "none"


def _metadata_source(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return ""
    return _safe_str(metadata.get("source") or metadata.get("memory_type")).lower()


class EchoWriteGate:
    """Echo／永迴軌寫入統一閘門。"""

    def __init__(self, host: Any = None):
        self.host = host
        self.version = ECHO_WRITE_GATE_VERSION

    def evaluate_turn_policy(
        self,
        *,
        final_response: str = "",
        user_input: str = "",
        turn_info: Optional[Dict[str, Any]] = None,
        session_state: Optional[Dict[str, Any]] = None,
        drift_info: Optional[Dict[str, Any]] = None,
        extracted_info: Optional[Dict[str, Any]] = None,
        risk_level: Optional[int] = None,
    ) -> EchoWriteDecision:
        """
        回合級：是否允許進入 generate_and_store。
        """
        response = final_response if isinstance(final_response, str) else _safe_str(final_response)
        text_in = user_input if isinstance(user_input, str) else _safe_str(user_input)
        notes: List[str] = []
        info = extracted_info if isinstance(extracted_info, dict) else {}
        turn = turn_info if isinstance(turn_info, dict) else {}
        state = session_state if isinstance(session_state, dict) else {}

        risk = risk_level
        if risk is None:
            risk = _safe_int(
                turn.get("risk_level", state.get("risk_level", info.get("risk_level", 0))),
                0,
            )
        policy = resolve_policy_level(info, state, turn)

        base = EchoWriteDecision(
            allowed=True,
            stage="pre_turn",
            response_chars=len(response),
            user_input_chars=len(text_in),
            policy_level=policy,
            risk_level=risk,
            notes=notes,
        )

        hooks = _extract_hooks(turn, state, info)
        if bool(hooks.get("skip_echo_consolidation")):
            base.allowed = False
            base.deny_reason = DENY_ORCHESTRATOR_HINT
            notes.append("orchestrator_hint_skip")
            return base

        if risk >= 4:
            base.allowed = False
            base.deny_reason = DENY_RISK_LEVEL
            notes.append(f"risk_level={risk}")
            return base

        alert = _resolve_drift_alert(drift_info, turn, info)
        if alert == "critical":
            base.allowed = False
            base.deny_reason = DENY_CRITICAL_DRIFT
            notes.append("critical_narrative_drift")
            return base

        intensity = _resolve_intensity(turn, state, info)
        if intensity == "crisis" and contains_autobiography_marker(response):
            base.allowed = False
            base.deny_reason = DENY_CRISIS_AUTOBIOGRAPHY
            notes.append("crisis_plus_autobiography_markers")
            return base

        if policy == "critical" and contains_autobiography_marker(response):
            base.allowed = False
            base.deny_reason = DENY_POLICY_CRITICAL_AUTOBIO
            notes.append("policy_critical_blocks_autobiography_echo")
            return base

        # 回應為空才在回合級拒絕；user_input 缺省交由 pre_store 再驗
        if not response.strip():
            base.allowed = False
            base.deny_reason = DENY_EMPTY_CONTENT
            notes.append("empty_response")
            return base

        if not text_in.strip():
            notes.append("user_input_missing_at_turn_policy")

        notes.append("turn_policy_pass")
        return base

    def evaluate_pre_store(
        self,
        *,
        user_input: str,
        response: str,
        echo_id: str = "",
        echo_score: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        extracted_info: Optional[Dict[str, Any]] = None,
        session_state: Optional[Dict[str, Any]] = None,
        turn_info: Optional[Dict[str, Any]] = None,
        drift_info: Optional[Dict[str, Any]] = None,
        risk_level: Optional[int] = None,
        force: bool = False,
    ) -> EchoWriteDecision:
        """
        落盤直前：再驗 id／source／分數／回合政策。
        force=True 時仍禁止正史 id／canon source／空內容（憲法優先）。
        """
        turn_decision = self.evaluate_turn_policy(
            final_response=response,
            user_input=user_input,
            turn_info=turn_info,
            session_state=session_state,
            drift_info=drift_info,
            extracted_info=extracted_info,
            risk_level=risk_level,
        )
        # force 僅可繞過「策略性 soft skip」，不可繞過憲法級拒絕
        if not turn_decision.allowed:
            constitutional = turn_decision.deny_reason in {
                DENY_EMPTY_CONTENT,
                DENY_CRISIS_AUTOBIOGRAPHY,
                DENY_POLICY_CRITICAL_AUTOBIO,
                DENY_CRITICAL_DRIFT,
            }
            soft = turn_decision.deny_reason in {
                DENY_ORCHESTRATOR_HINT,
                DENY_RISK_LEVEL,
            }
            if not (force and soft and not constitutional):
                turn_decision.stage = "pre_store"
                turn_decision.notes.append("pre_store_blocked_by_turn_policy")
                return turn_decision
            turn_decision.notes.append("force_soft_bypass")

        decision = EchoWriteDecision(
            allowed=True,
            stage="pre_store",
            response_chars=len(response or ""),
            user_input_chars=len(user_input or ""),
            policy_level=turn_decision.policy_level,
            risk_level=turn_decision.risk_level,
            echo_id=_safe_str(echo_id),
            notes=list(turn_decision.notes),
        )

        if not (user_input or "").strip() or not (response or "").strip():
            decision.allowed = False
            decision.deny_reason = DENY_EMPTY_CONTENT
            decision.notes.append("empty_user_or_response_at_pre_store")
            return decision

        if echo_score is not None:
            try:
                score = float(echo_score)
            except (TypeError, ValueError):
                decision.allowed = False
                decision.deny_reason = DENY_INVALID_ECHO_SCORE
                decision.notes.append("echo_score_not_numeric")
                return decision
            if not (0.0 <= score <= 1.0):
                decision.allowed = False
                decision.deny_reason = DENY_INVALID_ECHO_SCORE
                decision.notes.append(f"echo_score_out_of_range={score}")
                return decision
            decision.echo_score = score

        # 落盤前尚未產生 id：跳過 id 檢查（寫入後再用 validate_echo_id）
        if echo_id:
            id_check = self.validate_echo_id(echo_id)
            if not id_check.allowed:
                id_check.stage = "pre_store"
                id_check.response_chars = decision.response_chars
                id_check.user_input_chars = decision.user_input_chars
                id_check.policy_level = decision.policy_level
                id_check.echo_score = decision.echo_score
                id_check.notes = decision.notes + id_check.notes
                return id_check
        else:
            decision.notes.append("echo_id_pending")

        source = _metadata_source(metadata)
        if source in CANON_SOURCE_TOKENS:
            decision.allowed = False
            decision.deny_reason = DENY_CANON_SOURCE
            decision.notes.append(f"forbidden_source={source}")
            return decision

        # metadata 顯式宣稱可改寫正史 → 拒絕
        if isinstance(metadata, dict) and metadata.get("canon_mutable") is True:
            decision.allowed = False
            decision.deny_reason = DENY_CANON_SOURCE
            decision.notes.append("canon_mutable_true_forbidden")
            return decision

        decision.notes.append("pre_store_pass")
        return decision

    def validate_echo_id(self, echo_id: Any, *, require_nonempty: bool = True) -> EchoWriteDecision:
        mid = _safe_str(echo_id).strip()
        decision = EchoWriteDecision(
            allowed=True,
            stage="post_id",
            echo_id=mid,
            notes=[],
        )
        if not mid:
            if require_nonempty:
                decision.allowed = False
                decision.deny_reason = DENY_STORE_FAILED
                decision.notes.append("empty_echo_id")
            else:
                decision.notes.append("empty_echo_id_allowed_pending")
            return decision
        if is_immutable_soul_memory_id(mid):
            decision.allowed = False
            decision.deny_reason = DENY_IMMUTABLE_ID
            decision.notes.append("immutable_prefix")
            return decision
        # 建議 echo_ 前綴；非強制（相容舊資料），但記錄觀測
        if not mid.startswith("echo_"):
            decision.notes.append("nonstandard_echo_id_prefix")
        return decision

    def record_judge_deny(
        self,
        *,
        prior: Optional[EchoWriteDecision] = None,
        echo_score: float = 0.0,
        response: str = "",
        user_input: str = "",
    ) -> EchoWriteDecision:
        base = prior or EchoWriteDecision(allowed=False)
        return EchoWriteDecision(
            allowed=False,
            deny_reason=DENY_JUDGE_FALSE,
            policy_level=base.policy_level,
            stage="judge",
            response_chars=len(response or "") or base.response_chars,
            user_input_chars=len(user_input or "") or base.user_input_chars,
            echo_score=float(echo_score or 0.0),
            risk_level=base.risk_level,
            notes=list(base.notes) + ["judge_should_store_false"],
        )

    def merge_success(
        self,
        *,
        prior: EchoWriteDecision,
        echo_id: str,
        echo_score: float,
    ) -> EchoWriteDecision:
        post = self.validate_echo_id(echo_id)
        if not post.allowed:
            post.policy_level = prior.policy_level
            post.response_chars = prior.response_chars
            post.user_input_chars = prior.user_input_chars
            post.echo_score = float(echo_score or 0.0)
            post.risk_level = prior.risk_level
            post.notes = list(prior.notes) + post.notes + ["post_id_reject"]
            return post
        return EchoWriteDecision(
            allowed=True,
            deny_reason=ALLOW_REASON,
            policy_level=prior.policy_level,
            stage="stored",
            response_chars=prior.response_chars,
            user_input_chars=prior.user_input_chars,
            echo_id=_safe_str(echo_id),
            echo_score=float(echo_score or 0.0),
            risk_level=prior.risk_level,
            notes=list(prior.notes) + ["echo_stored"],
        )
