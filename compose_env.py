"""Load credential values from config/.env.compose (single source of truth).

Secrets must not be committed in docker-compose.yml, workflow YAML, or .py files.
Application code reads DB credentials via compose_or_env() -> app/config.py.

Resolution order (highest first):
  1. OS environment variable (explicit override)
  2. config/.env.compose (local dev, gitignored)
  3. config/.env.compose.ci (CI validation only, when VITA_USE_COMPOSE_CI=1)
  4. Empty default
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Dict, Optional

_COMPOSE_ENV_FILENAME = ".env.compose"
_COMPOSE_ENV_CI_FILENAME = ".env.compose.ci"
_CONFIG_DIR = "config"

_CREDENTIAL_KEYS = frozenset({
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DATABASE_URL",
})


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _compose_env_path(project_root: Optional[Path] = None) -> Path:
    root = project_root or _project_root()
    return root / _CONFIG_DIR / _COMPOSE_ENV_FILENAME


def _compose_env_ci_path(project_root: Optional[Path] = None) -> Path:
    root = project_root or _project_root()
    return root / _CONFIG_DIR / _COMPOSE_ENV_CI_FILENAME


def _normalize_compose_value(key: str, value: str) -> str:
    text = str(value).strip().strip('"').strip("'")
    if key in {"POSTGRES_PASSWORD", "DB_PASSWORD"} and text in {"0", "0.0"}:
        return "0000"
    return text


def _parse_env_file(path: Path) -> Dict[str, str]:
    """Parse KEY=VALUE lines from a dotenv-style file."""
    if not path.is_file():
        return {}

    parsed: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _CREDENTIAL_KEYS:
            parsed[key] = _normalize_compose_value(key, value.strip())
    return parsed


def _merge_aliases(merged: Dict[str, str]) -> Dict[str, str]:
    if "POSTGRES_PASSWORD" in merged and "DB_PASSWORD" not in merged:
        merged["DB_PASSWORD"] = merged["POSTGRES_PASSWORD"]
    if "POSTGRES_USER" in merged and "DB_USER" not in merged:
        merged["DB_USER"] = merged["POSTGRES_USER"]
    if "POSTGRES_DB" in merged and "DB_NAME" not in merged:
        merged["DB_NAME"] = merged["POSTGRES_DB"]
    if not merged.get("DATABASE_URL") and merged.get("DB_PASSWORD"):
        user = merged.get("DB_USER", "postgres")
        password = merged["DB_PASSWORD"]
        host = merged.get("DB_HOST", "postgres")
        port = merged.get("DB_PORT", "5432")
        name = merged.get("DB_NAME", "vita_db")
        merged["DATABASE_URL"] = (
            f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
        )
    return merged


@functools.lru_cache(maxsize=1)
def load_compose_environment(project_root: Optional[Path] = None) -> Dict[str, str]:
    """Load credential-related values from config/.env.compose (or CI file)."""
    root = project_root or _project_root()
    env_path = _compose_env_path(root)
    merged = _parse_env_file(env_path)

    if not merged and os.getenv("VITA_USE_COMPOSE_CI", "").lower() in {"1", "true", "yes"}:
        merged = _parse_env_file(_compose_env_ci_path(root))

    return _merge_aliases(merged)


def compose_or_env(key: str, default: str = "") -> str:
    """Return OS env if set, otherwise value from config/.env.compose."""
    explicit = os.getenv(key)
    if explicit is not None and explicit != "":
        return explicit

    compose = load_compose_environment()
    if key == "DB_PASSWORD":
        return compose.get("DB_PASSWORD") or compose.get("POSTGRES_PASSWORD", default)
    if key == "DB_USER":
        return compose.get("DB_USER") or compose.get("POSTGRES_USER", default)
    if key == "DB_NAME":
        return compose.get("DB_NAME") or compose.get("POSTGRES_DB", default)

    return compose.get(key, default)


def compose_env_file_for_docker(project_root: Optional[Path] = None) -> Path:
    """Return path passed to `docker compose --env-file` (must exist)."""
    root = project_root or _project_root()
    primary = _compose_env_path(root)
    if primary.is_file():
        return primary
    if os.getenv("VITA_USE_COMPOSE_CI", "").lower() in {"1", "true", "yes"}:
        return _compose_env_ci_path(root)
    return primary
