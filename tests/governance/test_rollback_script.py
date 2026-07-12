"""Contract tests for scripts/deploy/rollback.sh."""

from __future__ import annotations

from pathlib import Path


def test_rollback_script_waits_for_healthy_vita_api() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts/deploy/rollback.sh"
    ).read_text(encoding="utf-8")
    assert "up -d vita-api --no-build --wait" in script


def test_rollback_script_pins_vita_api_image_after_retag() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts/deploy/rollback.sh"
    ).read_text(encoding="utf-8")
    assert 'export VITA_API_IMAGE="vita-api:latest"' in script


def test_rollback_script_supports_compose_extra_files() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts/deploy/rollback.sh"
    ).read_text(encoding="utf-8")
    assert "COMPOSE_EXTRA_FILES" in script
