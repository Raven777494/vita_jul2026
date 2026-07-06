"""Tests for local DATABASE_URL resolution (stale OS env override)."""

from __future__ import annotations

import importlib


def _config_module():
    """Return app.config module (not the Config singleton on app.config)."""
    return importlib.import_module("app.config")


def test_resolve_database_url_ignores_os_database_url_in_local_dev(monkeypatch):
    cfg = _config_module()
    monkeypatch.setattr(cfg, "IS_PRODUCTION", False)
    monkeypatch.setattr(cfg, "IS_STAGING", False)
    monkeypatch.setattr(cfg, "IS_RUNNING_IN_DOCKER", False)
    monkeypatch.setattr(cfg, "IS_TESTING", False)
    # Pin DB_HOST/DB_PORT so the test does not depend on config/.env.local values.
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "5432")
    # Scanner-safe placeholder (change_me_*); must not appear in resolved URL.
    stale_password = "change_me_stale_os_password"
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:"
        + stale_password
        + "@127.0.0.1:5432/vita_db",
    )
    monkeypatch.setenv("DB_PASSWORD", stale_password)

    def fake_compose_file_credential(key, default=""):
        if key == "DB_PASSWORD":
            return "compose_secret"
        if key == "DB_USER":
            return "postgres"
        return default

    monkeypatch.setattr(cfg, "compose_file_credential", fake_compose_file_credential)
    monkeypatch.setattr(
        cfg,
        "compose_or_env",
        lambda key, default="": "vita_db" if key == "DB_NAME" else default,
    )

    url = cfg._resolve_database_url()
    assert "compose_secret" in url
    assert stale_password not in url
    assert url.endswith("@127.0.0.1:5432/vita_db")
