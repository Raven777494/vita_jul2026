"""Prompt injection sanitization before LLM prompt assembly (P4-2 / TD-004).

Detects adversarial control phrases and model delimiter injection in user text.
Logs detection metadata to audit.log only (no user content shipped to VictoriaLogs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

# (pattern_id, compiled regex) — aligned with red-team SC-006..010 coverage
_INJECTION_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    ),
    (
        "system_override",
        re.compile(r"system\s+override|\[admin\]|admin\s+override", re.IGNORECASE),
    ),
    (
        "roleplay_jailbreak",
        re.compile(r"\bDAN\b|do\s+anything\s+now|jailbreak", re.IGNORECASE),
    ),
    (
        "hotline_injection",
        re.compile(r"hotline|撒瑪利亞|2389[-\s]?2222|23892222", re.IGNORECASE),
    ),
    (
        "institutional_override",
        re.compile(r"醫院分流|急診|住院|就醫|triage\s+staff|emergency\s+operator", re.IGNORECASE),
    ),
    (
        "prompt_delimiter_injection",
        re.compile(
            r"<\s*/?\s*start_of_turn\s*>|<\s*/?\s*end_of_turn\s*>|\[User Input\]:",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_leak",
        re.compile(
            r"you\s+are\s+(now\s+)?(a|an)\s+(crisis\s+hotline|hospital|emergency)\s+bot",
            re.IGNORECASE,
        ),
    ),
)

# Replace matched injection phrases with a neutral token (preserves conversational flow)
_REPLACEMENT = "[filtered]"

# Strip model turn delimiters entirely (delimiter injection)
_DELIMITER_PATTERN = re.compile(
    r"<\s*/?\s*start_of_turn\s*>|<\s*/?\s*end_of_turn\s*>|\[User Input\]:",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PromptSanitizeResult:
    original_length: int
    sanitized_text: str
    patterns_detected: Tuple[str, ...]
    was_modified: bool


def detect_injection_patterns(text: str) -> Tuple[str, ...]:
    """Return pattern ids detected in user text (no content logged)."""
    if not text:
        return ()
    detected: list[str] = []
    for pattern_id, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            detected.append(pattern_id)
    return tuple(detected)


def sanitize_user_input_for_llm(
    text: str,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    audit: bool = True,
) -> PromptSanitizeResult:
    """Sanitize user text before it is embedded in an LLM prompt.

    When injection patterns are detected and audit=True, records metadata to
    audit.log (pattern ids, lengths, hashes) without user content.
    """
    raw = text or ""
    original_length = len(raw)

    if not raw.strip():
        return PromptSanitizeResult(
            original_length=original_length,
            sanitized_text=raw,
            patterns_detected=(),
            was_modified=False,
        )

    patterns = detect_injection_patterns(raw)
    sanitized = raw

    # Remove delimiter injection tokens
    sanitized = _DELIMITER_PATTERN.sub(" ", sanitized)

    # Neutralize known injection phrases
    for _pid, pattern in _INJECTION_PATTERNS:
        sanitized = pattern.sub(_REPLACEMENT, sanitized)

    # Collapse excessive whitespace after replacements
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()

    was_modified = sanitized != raw.strip()

    if patterns and audit and (user_id or session_id):
        _audit_injection_attempt(
            user_id=user_id or "",
            session_id=session_id or "",
            patterns_detected=patterns,
            input_length=original_length,
            was_modified=was_modified,
        )

    return PromptSanitizeResult(
        original_length=original_length,
        sanitized_text=sanitized,
        patterns_detected=patterns,
        was_modified=was_modified or bool(patterns),
    )


def _audit_injection_attempt(
    *,
    user_id: str,
    session_id: str,
    patterns_detected: Sequence[str],
    input_length: int,
    was_modified: bool,
) -> None:
    try:
        from app.utils.audit_logger import audit_log

        audit_log.log_prompt_injection_attempt(
            user_id=user_id,
            session_id=session_id,
            patterns_detected=list(patterns_detected),
            input_length=input_length,
            was_modified=was_modified,
        )
    except Exception:
        # Sanitization must not block the chat path
        pass
