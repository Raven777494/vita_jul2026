"""Tests for scripts/deploy/write_compose_env.py."""

from __future__ import annotations

from pathlib import Path

from scripts.deploy.write_compose_env import write_compose_env

_REQUIRED_KEYS = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "GRAFANA_ADMIN_PASSWORD",
    "N8N_BASIC_AUTH_USER",
    "N8N_BASIC_AUTH_PASSWORD",
    "N8N_ENCRYPTION_KEY",
    "JWT_SECRET",
    "ENCRYPT_KEY",
    "SECRET_KEY",
    "API_KEY",
)


def _set_required_env(monkeypatch) -> None:
    values = {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "staging_postgres_password_32chars",
        "POSTGRES_DB": "vita_db",
        "DB_USER": "postgres",
        "DB_PASSWORD": "staging_postgres_password_32chars",
        "DB_HOST": "postgres",
        "DB_PORT": "5432",
        "DB_NAME": "vita_db",
        "GRAFANA_ADMIN_PASSWORD": "staging_grafana_password_32chars",
        "N8N_BASIC_AUTH_USER": "admin",
        "N8N_BASIC_AUTH_PASSWORD": "staging_n8n_password_32chars",
        "N8N_ENCRYPTION_KEY": "staging_n8n_encryption_key_32_chars",
        "JWT_SECRET": "staging_jwt_secret_minimum_32_characters",
        "ENCRYPT_KEY": "staging_encrypt_key_minimum_32_characters",
        "SECRET_KEY": "staging_secret_key_minimum_32_characters",
        "API_KEY": "staging_api_key_minimum_32_characters_long",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_require_all_accepts_database_url_parts_without_database_url(
    monkeypatch, tmp_path: Path
) -> None:
    _set_required_env(monkeypatch)
    target = tmp_path / "config" / ".env.compose"

    rc = write_compose_env(target, require_all=True, allow_missing=False)

    assert rc == 0
    content = target.read_text(encoding="utf-8")
    assert "DATABASE_URL=postgresql+psycopg2://" in content


def test_require_all_fails_when_database_url_parts_missing(monkeypatch, tmp_path: Path) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("DB_HOST", raising=False)
    target = tmp_path / "config" / ".env.compose"

    rc = write_compose_env(target, require_all=True, allow_missing=False)

    assert rc == 1


def test_require_all_lists_all_missing_keys(monkeypatch, tmp_path: Path) -> None:
    for key in _REQUIRED_KEYS + ("DATABASE_URL",):
        monkeypatch.delenv(key, raising=False)
    target = tmp_path / "config" / ".env.compose"

    rc = write_compose_env(target, require_all=True, allow_missing=False)

    assert rc == 1
