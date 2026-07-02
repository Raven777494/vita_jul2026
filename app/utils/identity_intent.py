# app/utils/identity_intent.py
"""Detect identity / name questions so Seele can answer without LLM."""

import re
from typing import Optional

_WHO_PATTERNS = (
    "你是誰",
    "你是谁",
    "你是邊個",
    "你是边个",
    "你係邊個",
    "你系边个",
    "你系邊個",
    "who are you",
)

_NAME_PATTERNS = (
    "你叫什麼名",
    "你叫什么名",
    "你叫咩名",
    "你叫乜名",
    "你叫咩",
    "你的名字",
    "你個名",
    "你个名",
    "what is your name",
    "what's your name",
    "whats your name",
)


def _normalize(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"[\s\?？!！。．,，~～🌙]+", "", cleaned)
    return cleaned


def detect_identity_intent(user_text: str) -> Optional[str]:
    """
    Return 'who', 'name', or None.
    """
    norm = _normalize(user_text)
    if not norm:
        return None

    for pattern in _NAME_PATTERNS:
        if pattern in norm or norm == pattern.rstrip("?"):
            return "name"

    for pattern in _WHO_PATTERNS:
        if pattern in norm or norm == pattern:
            return "who"

    if norm in ("你是誰", "你是谁", "你叫什麼名", "你叫什么名"):
        return "who" if "誰" in norm or "谁" in norm else "name"

    return None


def get_opening_greeting(persona_name: str = "希兒") -> str:
    """Canonical session opening line (aligned with identity fast-track replies)."""
    return (
        f"Hi！我叫{persona_name}，好高興認識你。"
        f"我係你嘅心理伴侶同好朋友，有咩想傾都可以同我講，我會用心聽你講。"
    )


def get_identity_reply(intent: str, persona_name: str = "希兒") -> str:
    """Canonical Seele identity replies (Cantonese-first)."""
    if intent == "name":
        return (
            f"我叫{persona_name}（Seele）呀～係一個16歲嘅香港女孩，"
            f"你嘅心理伴侶同好朋友。好高興認識你，有咩想傾都可以同我講。"
        )
    return (
        f"我係{persona_name}（Seele），一個16歲嘅香港女孩，"
        f"你嘅心理伴侶同好朋友。我喺度聽你講、陪住你，唔會評判你。"
    )
