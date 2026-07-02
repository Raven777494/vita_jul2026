"""Conditional Meta Auditor (Llama 8082) gate for v9 pipeline."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

CBT_LOGIC_KEYWORDS = (
    "點解",
    "为什么",
    "為什麼",
    "點算",
    "怎么办",
    "怎麼辦",
    "認知",
    "扭曲",
    "cbt",
    "邏輯",
    "分析",
    "reasoning",
    "help me think",
)

MEMORY_CONFLICT_KEYWORDS = (
    "你唔記得",
    "你不记得",
    "上次話",
    "上次说",
    "明明話過",
    "memory",
    "記錯",
)


def should_run_meta_audit(
    *,
    user_text: str,
    risk_level: int,
    emotion_profile: Optional[Dict[str, Any]] = None,
    memory_context: str = "",
    audit_enabled: bool = True,
    risk_threshold: int = 3,
    primary_response: str = "",
) -> Tuple[bool, str]:
    """
    Decide whether Llama Meta Auditor (8082) should run.

    Returns (should_audit, reason).
    """
    if not audit_enabled:
        return False, "audit_disabled"

    emotion_profile = emotion_profile or {}
    text_lower = (user_text or "").lower()

    if risk_level >= risk_threshold:
        return True, f"risk_level>={risk_threshold}"

    if emotion_profile.get("is_crisis_risk"):
        return True, "crisis_signal"

    if any(kw in user_text or kw in text_lower for kw in CBT_LOGIC_KEYWORDS):
        return True, "cbt_or_complex_logic"

    if any(kw in user_text for kw in MEMORY_CONFLICT_KEYWORDS):
        return True, "memory_conflict_signal"

    if memory_context and any(
        kw in user_text for kw in ("記得", "记得", "之前", "上次")
    ):
        return True, "memory_recall_turn"

    # Short or evasive primary draft from Nemo — worth auditing
    primary = (primary_response or "").strip()
    if primary and len(primary) < 20:
        return True, "primary_response_short"

    return False, "audit_not_required"


def extract_critic_score(meta_audit: Optional[Dict[str, Any]]) -> Optional[float]:
    """Map audit JSON to a single quality score (critic.score)."""
    if not meta_audit:
        return None
    for key in ("response_quality", "empathy_score", "critic_score"):
        if key in meta_audit and meta_audit[key] is not None:
            try:
                return float(meta_audit[key])
            except (TypeError, ValueError):
                continue
    return None


def should_regenerate_nemo(
    *,
    critic_score: Optional[float],
    quality_threshold: float,
    revised_text: str,
    min_len: int,
    main_llm_ok: bool,
    regen_count: int,
    max_regen: int = 1,
    risk_missed: bool = False,
) -> bool:
    """True when audit failed quality gate and Nemo regen is allowed."""
    if not main_llm_ok or regen_count >= max_regen:
        return False
    revised = (revised_text or "").strip()
    if len(revised) >= min_len:
        return False
    if risk_missed:
        return True
    if critic_score is None or critic_score >= quality_threshold:
        return False
    return True


def build_turn_meta_layer(
    *,
    meta_audit: Optional[Dict[str, Any]] = None,
    audit_ran: bool = False,
    audit_reason: Optional[str] = None,
    nemo_regenerated: bool = False,
    pipeline_stages: Optional[list] = None,
) -> Dict[str, Any]:
    """Normalized post-turn Meta Layer JSON for persistence and /health analytics."""
    critic = extract_critic_score(meta_audit)
    layer: Dict[str, Any] = {
        "empathy_score": None,
        "risk_missed": False,
        "response_quality": None,
        "critic_score": critic,
        "audit_ran": audit_ran,
        "audit_reason": audit_reason,
        "nemo_regenerated": nemo_regenerated,
        "pipeline_stages": list(pipeline_stages or []),
    }
    if meta_audit:
        for key in ("empathy_score", "risk_missed", "response_quality"):
            if key in meta_audit:
                layer[key] = meta_audit[key]
        if layer["critic_score"] is None:
            layer["critic_score"] = extract_critic_score(meta_audit)
    return layer


def parse_meta_audit_json(content: str) -> Optional[Dict[str, Any]]:
    """Extract Meta Auditor JSON from Llama output."""
    import json
    import re

    if not content:
        return None
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        blob = match.group(0).replace("\n", " ")
        blob = re.sub(r",\s*}", "}", blob)
        return json.loads(blob)
    except json.JSONDecodeError:
        return None

