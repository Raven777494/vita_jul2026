"""Tests for GitHub Actions security and deploy secrets contract verifiers."""

from __future__ import annotations

from pathlib import Path

from scripts.governance.verify_deploy_secrets_contract import verify_contract
from scripts.governance.verify_github_workflows import verify_workflows


def test_verify_github_workflows_passes_on_repo_workflows() -> None:
    root = Path(__file__).resolve().parents[2]
    errors, notes = verify_workflows(root)
    assert not errors, errors
    assert any("actions/checkout@v4" in note for note in notes)


def test_verify_deploy_secrets_contract_passes() -> None:
    root = Path(__file__).resolve().parents[2]
    errors = verify_contract(root)
    assert errors == []


def test_verify_github_workflows_scripts_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts/governance/verify_github_workflows.py").is_file()
    assert (root / "scripts/governance/verify_deploy_secrets_contract.py").is_file()
    assert (root / "docs/operations/github-setup-c-zone.md").is_file()
