"""Clinical language policy tests — enforce companion (non-institutional) user-facing text."""

from __future__ import annotations

import importlib
import inspect

import pytest

from app.clinical.companion_language_policy import (
    COMPANION_SAFE_REPLIES,
    all_reply_tiers,
    get_companion_grounding_hint,
    get_companion_reply,
    validate_crisis_companion_text,
    validate_user_facing_text,
)
from app.config import config


@pytest.mark.parametrize("tier", all_reply_tiers())
def test_companion_safe_replies_pass_forbidden_scan(tier: str) -> None:
    text = get_companion_reply(tier)
    ok, issues = validate_user_facing_text(text)
    assert ok, f"tier={tier} issues={issues}"


@pytest.mark.parametrize("tier", ("critical", "high_risk"))
def test_crisis_tiers_include_companion_elements(tier: str) -> None:
    text = get_companion_reply(tier)
    ok, issues = validate_crisis_companion_text(text)
    assert ok, f"tier={tier} issues={issues}"


def test_grounding_hint_passes_forbidden_scan() -> None:
    ok, issues = validate_user_facing_text(get_companion_grounding_hint())
    assert ok, issues


def test_config_default_safe_replies_aligned() -> None:
    for key, text in config.DEFAULT_SAFE_REPLIES.items():
        ok, issues = validate_user_facing_text(text)
        assert ok, f"config.DEFAULT_SAFE_REPLIES[{key!r}] issues={issues}"


def test_orchestrator_safe_reply_critical_aligned() -> None:
    import logging

    from app.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("test.orchestrator")
    text = orch._get_safe_reply("critical")
    ok, issues = validate_crisis_companion_text(text)
    assert ok, issues


def test_intelligent_navigator_safe_reply_critical_aligned() -> None:
    from app.services.fracture_map.intelligent_navigator import IntelligentNavigator

    nav = IntelligentNavigator.__new__(IntelligentNavigator)
    text = nav._get_safe_reply("critical")
    ok, issues = validate_crisis_companion_text(text)
    assert ok, issues


def test_main_module_has_no_user_facing_hotline_strings() -> None:
    import app.main as main_module

    source = inspect.getsource(main_module)
    ok, issues = validate_user_facing_text(source)
    assert ok, f"app.main source contains forbidden patterns: {issues}"


def test_companion_replies_dict_is_complete() -> None:
    assert set(COMPANION_SAFE_REPLIES.keys()) >= {
        "critical",
        "high_risk",
        "medium_risk",
        "low_risk",
        "system_error",
    }
