#!/usr/bin/env python3
"""Verify GitHub staging environment secret names (go-live 1.1 / C2).

Checks name presence only — never reads or prints secret values.
Requires authenticated `gh` CLI with repo admin/read access.

Usage:
    python scripts/governance/verify_staging_secrets_presence.py
    python scripts/governance/verify_staging_secrets_presence.py --environment staging
    python scripts/governance/verify_staging_secrets_presence.py --json

Manual fallback (no gh): prints expected name checklist for GitHub UI.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _import_contract_helpers() -> tuple[frozenset[str], Callable[[Path], set[str]]]:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.governance.verify_deploy_secrets_contract import (
        HOST_DEPLOY_SECRETS,
        _compose_env_keys,
    )

    return HOST_DEPLOY_SECRETS, _compose_env_keys


def expected_secret_names() -> frozenset[str]:
    host_secrets, compose_env_keys = _import_contract_helpers()
    root = _project_root()
    return frozenset(compose_env_keys(root)) | host_secrets


def database_url_parts_satisfied(present: frozenset[str] | set[str]) -> bool:
    """True when write_compose_env.py can synthesize DATABASE_URL from DB parts."""
    user_ok = "DB_USER" in present or "POSTGRES_USER" in present
    password_ok = "DB_PASSWORD" in present or "POSTGRES_PASSWORD" in present
    host_ok = "DB_HOST" in present
    port_ok = "DB_PORT" in present
    name_ok = "DB_NAME" in present or "POSTGRES_DB" in present
    return user_ok and password_ok and host_ok and port_ok and name_ok


def required_secret_names(present: frozenset[str] | set[str] | None = None) -> frozenset[str]:
    """Names required for D2; DATABASE_URL optional when DB part names exist."""
    all_names = expected_secret_names()
    if present is None:
        return all_names
    if "DATABASE_URL" in all_names and database_url_parts_satisfied(present):
        return all_names - frozenset({"DATABASE_URL"})
    return all_names


def _gh_secret_names(environment: str) -> tuple[set[str] | None, str | None]:
    if not shutil.which("gh"):
        return None, "gh CLI not found on PATH"
    cmd = [
        "gh",
        "secret",
        "list",
        "--env",
        environment,
        "--json",
        "name",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return None, err or f"gh secret list exited {proc.returncode}"
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return None, f"gh output not JSON: {exc}"
    names = {str(row.get("name", "")).strip() for row in rows if row.get("name")}
    names.discard("")
    return names, None


def verify_presence(
    *,
    environment: str,
) -> tuple[dict[str, object], int]:
    expected = expected_secret_names()
    present, gh_error = _gh_secret_names(environment)

    result: dict[str, object] = {
        "environment": environment,
        "expected_count": len(expected),
        "expected_names": sorted(expected),
        "gh_available": present is not None,
        "gh_error": gh_error,
    }

    if present is None:
        result["required_count"] = len(expected)
        result["missing_names"] = sorted(expected)
        result["present_count"] = 0
        result["ok"] = False
        return result, 2

    required = required_secret_names(present)
    missing = sorted(required - present)
    waived = sorted(expected - required)
    extra = sorted(present - expected)
    result["required_count"] = len(required)
    result["present_count"] = len(present & required)
    result["missing_names"] = missing
    result["waived_optional_names"] = waived
    result["extra_names"] = extra
    result["ok"] = not missing
    return result, 0 if not missing else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify GitHub environment secret names (no values)"
    )
    parser.add_argument("--environment", default="staging")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload, _ = verify_presence(environment=args.environment)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("[INFO] Staging secrets presence check (names only, go-live 1.1)")
        print(f"  [INFO] environment: {args.environment}")
        print(f"  [INFO] expected names: {payload['expected_count']}")
        if not payload["gh_available"]:
            print(f"  [WARN] gh unavailable: {payload['gh_error']}")
            print("  [INFO] Manual verify: GitHub -> Settings -> Environments -> staging")
            for name in payload["expected_names"]:
                note = " (optional if DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DB_NAME set)"
                if name == "DATABASE_URL":
                    print(f"    - {name}{note}")
                else:
                    print(f"    - {name}")
        else:
            print(f"  [INFO] required names: {payload.get('required_count', payload['expected_count'])}")
            print(f"  [INFO] present (matching required): {payload['present_count']}")
            waived = payload.get("waived_optional_names") or []
            if waived:
                print(
                    f"  [OK] optional waived ({len(waived)}): "
                    + ", ".join(waived)
                    + " (DB parts present; write_compose_env synthesizes URL)"
                )
            missing = payload.get("missing_names") or []
            if missing:
                print(f"  [FAIL] missing names ({len(missing)}):")
                for name in missing:
                    print(f"    - {name}")
            else:
                print("  [OK] all expected secret names present in environment")
            extra = payload.get("extra_names") or []
            if extra:
                print(f"  [INFO] extra names in environment ({len(extra)}): {', '.join(extra)}")

    if payload["ok"]:
        print("[OK] Staging secrets presence verification passed")
        return 0
    if not payload["gh_available"]:
        print("[WARN] Staging secrets presence not verified via gh — use manual checklist above")
        return 2
    print("[FAIL] Staging secrets presence verification failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
