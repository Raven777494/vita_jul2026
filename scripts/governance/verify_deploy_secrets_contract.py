#!/usr/bin/env python3
"""Verify deploy.yml secret names match write_compose_env and documentation.

Ensures GitHub Encrypted Secrets contract is consistent across:
  - .github/workflows/deploy.yml
  - scripts/deploy/write_compose_env.py
  - docs/operations/deploy.md

Usage:
    python scripts/governance/verify_deploy_secrets_contract.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _compose_env_keys(root: Path) -> set[str]:
    text = (root / "scripts" / "deploy" / "write_compose_env.py").read_text(encoding="utf-8")
    block = re.search(r"_ENV_KEYS\s*=\s*\((.*?)\)", text, re.DOTALL)
    if not block:
        raise ValueError("write_compose_env.py: _ENV_KEYS not found")
    return set(re.findall(r'"([A-Z0-9_]+)"', block.group(1)))


def _deploy_yml_secret_refs(root: Path) -> set[str]:
    deploy = root / ".github" / "workflows" / "deploy.yml"
    content = deploy.read_text(encoding="utf-8")
    return set(re.findall(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}", content))


HOST_DEPLOY_SECRETS = frozenset({"DEPLOY_HOST", "DEPLOY_KEY", "DEPLOY_USER", "DEPLOY_PATH"})


def verify_contract(root: Path | None = None) -> list[str]:
    root = root or _project_root()
    errors: list[str] = []

    compose_keys = _compose_env_keys(root)
    yml_secrets = _deploy_yml_secret_refs(root)

    missing_in_yml = compose_keys - yml_secrets
    if missing_in_yml:
        errors.append(
            "deploy.yml missing secrets for compose keys: "
            + ", ".join(sorted(missing_in_yml))
        )

    extra_compose = yml_secrets - compose_keys - HOST_DEPLOY_SECRETS
    if extra_compose:
        errors.append(
            "deploy.yml references unknown compose secrets: "
            + ", ".join(sorted(extra_compose))
        )

    missing_host = HOST_DEPLOY_SECRETS - yml_secrets
    if missing_host:
        errors.append(
            "deploy.yml missing host deploy secrets: "
            + ", ".join(sorted(missing_host))
        )

    deploy_md = (root / "docs" / "operations" / "deploy.md").read_text(encoding="utf-8")
    for key in sorted(compose_keys | HOST_DEPLOY_SECRETS):
        if f"`{key}`" not in deploy_md:
            errors.append(f"deploy.md missing documented secret `{key}`")

    return errors


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    print("[INFO] Deploy secrets contract verification")
    try:
        errors = verify_contract(root)
    except (FileNotFoundError, ValueError) as exc:
        print(f"  [FAIL] {exc}", file=sys.stderr)
        return 1

    if errors:
        for msg in errors:
            print(f"  [FAIL] {msg}", file=sys.stderr)
        print("[FAIL] Deploy secrets contract verification failed", file=sys.stderr)
        return 1

    print("  [OK] deploy.yml secrets align with write_compose_env.py")
    print("  [OK] deploy.md documents all required secret names")
    print("[OK] Deploy secrets contract verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
