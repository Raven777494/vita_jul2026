"""Tests for compose_env credential loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from compose_env import compose_env_file_for_docker, compose_or_env, load_compose_environment

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CI_ENV_TEXT = (_PROJECT_ROOT / "config" / ".env.compose.ci").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_compose_cache():
    load_compose_environment.cache_clear()
    yield
    load_compose_environment.cache_clear()


def _write_ci_env(project_root: Path) -> None:
    target = project_root / "config" / ".env.compose.ci"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_CI_ENV_TEXT, encoding="utf-8")


def test_load_from_ci_env_file(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("VITA_USE_COMPOSE_CI", "1")
    _write_ci_env(tmp_path)

    env = load_compose_environment(project_root=tmp_path)
    password = env.get("DB_PASSWORD") or env.get("POSTGRES_PASSWORD", "")
    assert password == "ci_compose_test_password"
    assert env.get("DB_USER") == "postgres"
    assert "ci_compose_test_password" in env.get("DATABASE_URL", "")


def test_os_env_overrides_compose_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VITA_USE_COMPOSE_CI", "1")
    monkeypatch.setenv("DB_PASSWORD", "override_from_os")
    _write_ci_env(tmp_path)

    assert compose_or_env("DB_PASSWORD") == "override_from_os"


def test_normalize_yaml_style_zero_password_in_env_file(tmp_path: Path, monkeypatch):
    env_file = tmp_path / "config" / ".env.compose"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("POSTGRES_PASSWORD=0\nDB_USER=postgres\n", encoding="utf-8")

    monkeypatch.delenv("VITA_USE_COMPOSE_CI", raising=False)
    env = load_compose_environment(project_root=tmp_path)
    assert env.get("POSTGRES_PASSWORD") == "0000"
    assert env.get("DB_PASSWORD") == "0000"


def test_compose_env_file_for_docker_prefers_local(monkeypatch, tmp_path: Path):
    local = tmp_path / "config" / ".env.compose"
    local.parent.mkdir(parents=True)
    local.write_text("POSTGRES_PASSWORD=local\n", encoding="utf-8")
    monkeypatch.delenv("VITA_USE_COMPOSE_CI", raising=False)

    assert compose_env_file_for_docker(tmp_path) == local
