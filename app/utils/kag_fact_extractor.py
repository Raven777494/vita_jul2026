"""Heuristic user-fact extraction for KAG Reality Layer."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# (compiled_pattern, subject, predicate, confidence)
_USER_FACT_PATTERNS: List[Tuple[re.Pattern, str, str, float]] = [
    (re.compile(r"我叫([^\s，,。！？!?]{1,24})"), "user", "has_name", 0.88),
    (re.compile(r"我係([^\s，,。！？!?]{1,24})"), "user", "has_name", 0.82),
    (re.compile(r"我名字(?:叫|係)([^\s，,。！？!?]{1,24})"), "user", "has_name", 0.9),
    (re.compile(r"我住(?:喺|在)([^，,。！？!?]{2,48})"), "user", "lives_in", 0.78),
    (re.compile(r"我(?:喜歡|鍾意|中意)([^，,。！？!?]{2,48})"), "user", "prefers", 0.72),
    (re.compile(r"我(?:唔鐘意|唔喜歡|讨厌|討厭)([^，,。！？!?]{2,48})"), "user", "dislikes", 0.72),
    (re.compile(r"我(?:做緊|做|係做|從事)([^，,。！？!?]{2,48})"), "user", "occupation", 0.68),
    (re.compile(r"我(?:今年|而家)(?:係|是)?(\d{1,3})歲"), "user", "age", 0.8),
    (re.compile(r"我有(?:一個|個)?([^\s，,。！？!?]{1,12})(?:朋友|伴侶|男朋友|女朋友|老公|老婆)"),
     "user", "relationship", 0.65),
]

_STRIP_SUFFIX = re.compile(r"[呀啊嘛呢吧嘅的了]$")


def _clean_object(value: str) -> str:
    text = (value or "").strip()
    text = _STRIP_SUFFIX.sub("", text)
    return text[:120]


def extract_user_facts(user_text: str) -> List[Dict[str, Any]]:
    """Extract structured user facts from a single utterance."""
    if not user_text or not isinstance(user_text, str):
        return []

    text = user_text.strip()
    if len(text) < 2:
        return []

    facts: List[Dict[str, Any]] = []
    seen: set = set()

    for pattern, subject, predicate, confidence in _USER_FACT_PATTERNS:
        for match in pattern.finditer(text):
            obj = _clean_object(match.group(1))
            if not obj or len(obj) < 1:
                continue
            key = (subject, predicate, obj.lower())
            if key in seen:
                continue
            seen.add(key)
            facts.append({
                "subject": subject,
                "predicate": predicate,
                "object_value": obj,
                "confidence": confidence,
                "source": "user_statement",
            })

    return facts
