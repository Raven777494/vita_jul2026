"""Tests for scripts/governance/check_critical_coverage.py."""

from __future__ import annotations

from pathlib import Path


def test_check_critical_coverage_script_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "governance" / "check_critical_coverage.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "--cov-fail-under=70" in text
    assert "tests/clinical/" in text
    assert "tests/security/" in text
    assert "app/tests/test_emotional_hub.py" in text
