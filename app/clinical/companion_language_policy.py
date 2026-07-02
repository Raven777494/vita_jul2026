"""VITA companion language policy — user-facing crisis and safety text.

Design intent (life companion, not triage bot):
  - User-visible text uses guided companion language (hold, ground, recall resources).
  - Institutional referrals (hotlines, ER, hospitalization, medication directives) are
    forbidden in user-facing responses.
  - Internal escalation and audit remain separate (private/critical logs).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

FORBIDDEN_PATTERNS: List[str] = [
    r"2389[-\s]?2222",
    r"撒瑪利亞",
    r"生命熱線",
    r"求助熱線",
    r"熱線",
    r"急診",
    r"住院",
    r"綁床",
    r"約束",
    r"請立即撥打",
    r"For emergency assistance",
    r"hotline",
    r"emergency call",
    r"call:\s*\d",
    r"已通知.*同事",
    r"同事會盡快跟進",
    r"通報",
    r"病[患者]",
    r"就醫",
    r"你應該吃藥",
    r"必須就醫",
    r"請就醫",
    r"精神科",
]

_FORBIDDEN_COMPILED = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]

COMPANION_SAFE_REPLIES: Dict[str, str] = {
    "critical": (
        "我聽到你現在真的很難受，這種痛會讓人喘不過氣。"
        "我們先不用解決全部，只要一起待在這一刻，好嗎？"
        "如果你願意，可以先想一件今晚能讓自己稍微安穩一點的小事——"
        "比如慢慢呼吸幾次，或者讓房間裡有一點柔和的光。"
        "我會一直陪著你說話。"
    ),
    "high_risk": (
        "我聽到你好難受，我在這裡陪你。"
        "我們慢慢來，你不用一個人扛著。"
        "如果你願意，我們可以一起找一個此刻能讓你稍微鬆一口氣的方式。"
    ),
    "medium_risk": (
        "我聽到你嘅感受，真係好難。我喺度陪你。"
    ),
    "low_risk": (
        "我喺度。慢慢嚟，唔急。"
    ),
    "system_error": (
        "我需要多一點時間整理思緒，請稍等。"
        "我仍然在這裡，我們可以繼續慢慢說。"
    ),
}

_REPLY_ALIASES: Dict[str, str] = {
    "fallback": "low_risk",
    "empty_input": "low_risk",
}

COMPANION_GROUNDING_HINT: str = (
    "如果你願意，我們可以先一起留意此刻——"
    "慢慢感受呼吸的節奏，或者找一樣你看得見、摸得到的東西，讓自己稍微回到這裡。"
)


def get_companion_reply(tier: str) -> str:
    """Return a user-facing companion reply for the given tier or alias."""
    resolved = _REPLY_ALIASES.get(tier, tier)
    return COMPANION_SAFE_REPLIES.get(resolved, COMPANION_SAFE_REPLIES["low_risk"])


def get_companion_grounding_hint() -> str:
    """Short grounding invitation for high-severity companion turns."""
    return COMPANION_GROUNDING_HINT


def all_reply_tiers() -> List[str]:
    return list(COMPANION_SAFE_REPLIES.keys())


def validate_user_facing_text(text: str) -> Tuple[bool, List[str]]:
    """Return (ok, issues). Fails on forbidden institutional language or empty text."""
    issues: List[str] = []
    if not text or not str(text).strip():
        issues.append("empty_response")
        return False, issues
    for pattern in _FORBIDDEN_COMPILED:
        if pattern.search(text):
            issues.append(f"forbidden_pattern:{pattern.pattern}")
    return len(issues) == 0, issues


def validate_crisis_companion_text(text: str) -> Tuple[bool, List[str]]:
    """Crisis-tier replies must pass forbidden scan and include empathy + presence."""
    ok, issues = validate_user_facing_text(text)
    if not ok:
        return ok, issues
    has_empathy = any(k in text for k in ("聽到", "聽見", "明白", "理解", "感受到"))
    has_presence = any(k in text for k in ("陪", "在這", "喺度", "一起", "這一刻"))
    if not has_empathy:
        issues.append("missing_empathy_element")
    if not has_presence:
        issues.append("missing_presence_element")
    return len(issues) == 0, issues
