"""Tests for D-zone staging deploy verification."""

from __future__ import annotations

from pathlib import Path

from scripts.governance.verify_deploy_d_zone import verify_contract


def test_verify_deploy_d_zone_passes() -> None:
    root = Path(__file__).resolve().parents[2]
    errors, notes = verify_contract(root)
    assert not errors, errors
    assert any("deploy-d-zone.md" in note for note in notes)


def test_deploy_workflow_pins_setup_python() -> None:
    root = Path(__file__).resolve().parents[2]
    deploy = (root / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    assert deploy.count("actions/setup-python@v5") >= 2
    assert "actions/checkout@v4" in deploy


def test_ssh_compose_deploy_builds_postgres() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/deploy/ssh_compose_deploy.sh").read_text(encoding="utf-8")
    assert "build postgres" in script
    assert "--wait" in script


def test_hss_local_deploy_script_references() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/deploy/hss_local_deploy.ps1").read_text(encoding="utf-8")
    assert "smoke_check.sh" in script
    assert ".env.compose.backup" in script
    assert "git pull" in script
