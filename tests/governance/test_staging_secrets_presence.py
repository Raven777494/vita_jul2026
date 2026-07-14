"""Tests for staging secrets presence verifier."""

from __future__ import annotations

from pathlib import Path

from scripts.governance.verify_staging_secrets_presence import (
    database_url_parts_satisfied,
    expected_secret_names,
    required_secret_names,
    verify_presence,
)


def test_expected_secret_names_count() -> None:
    names = expected_secret_names()
    assert len(names) == 21
    assert "DEPLOY_HOST" in names
    assert "API_KEY" in names
    assert "POSTGRES_USER" in names


def test_database_url_optional_when_db_parts_present() -> None:
    present = {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DEPLOY_HOST",
        "DEPLOY_KEY",
    }
    assert database_url_parts_satisfied(present)
    required = required_secret_names(present)
    assert "DATABASE_URL" not in required


def test_database_url_required_when_db_parts_missing() -> None:
    present = {"DB_HOST", "DB_PORT", "POSTGRES_USER"}
    assert not database_url_parts_satisfied(present)
    required = required_secret_names(present)
    assert "DATABASE_URL" in required


def test_verify_presence_without_gh_returns_manual_mode() -> None:
    payload, _ = verify_presence(environment="staging")
    if payload["gh_available"]:
        return
    assert payload["ok"] is False
    assert payload["expected_count"] == 21
    assert len(payload["missing_names"]) == 21


def test_staging_secrets_script_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts/governance/verify_staging_secrets_presence.py").is_file()
    assert (root / "scripts/deploy/hss_local_deploy.ps1").is_file()
