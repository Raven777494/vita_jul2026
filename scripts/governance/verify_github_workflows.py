#!/usr/bin/env python3
"""Verify GitHub Actions workflows follow VITA security policy (C-zone).

Rules enforced:
  1. Only Verified Creator actions from the `actions` organization.
  2. Pin major version tags (vN) — never @main / @master / @develop.
  3. No secret literals in workflow YAML (only ${{ secrets.* }} references).

Usage:
    python scripts/governance/verify_github_workflows.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

USES_LINE = re.compile(r"^\s*uses:\s*(?P<ref>.+?)\s*(?:#.*)?$", re.MULTILINE)
SECRETS_REF = re.compile(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}")
FORBIDDEN_USE_TAGS = ("@main", "@master", "@develop", "@HEAD", "@latest")
ALLOWED_ACTION_PREFIX = "actions/"
LOCAL_ACTION_PREFIX = "./"
DOCKER_USE_PREFIX = "docker://"

# Patterns that suggest hardcoded credentials in workflow YAML (not ${{ secrets.* }})
HARDCODED_SECRET_PATTERNS = (
    re.compile(r"password:\s*['\"][^'\"${}]{8,}['\"]", re.IGNORECASE),
    re.compile(r"api[_-]?key:\s*['\"][^'\"${}]{16,}['\"]", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workflow_files(root: Path) -> list[Path]:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    return sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml"))


def _validate_uses(ref: str, *, rel_path: str, line_hint: str) -> list[str]:
    errors: list[str] = []
    ref = ref.strip().strip("'\"")
    if ref.startswith(DOCKER_USE_PREFIX) or ref.startswith(LOCAL_ACTION_PREFIX):
        return errors
    for forbidden in FORBIDDEN_USE_TAGS:
        if forbidden in ref:
            errors.append(
                f"{rel_path}: uses {ref!r} — forbidden floating tag {forbidden!r}; pin actions/@vN"
            )
            break
    if not ref.startswith(ALLOWED_ACTION_PREFIX):
        errors.append(
            f"{rel_path}: uses {ref!r} — only Verified Creator actions/* allowed "
            "(no third-party Marketplace actions)"
        )
        return errors
    if "@" not in ref:
        errors.append(f"{rel_path}: uses {ref!r} — missing version pin (@vN or commit SHA)")
    else:
        _action, tag = ref.rsplit("@", 1)
        if tag in ("main", "master", "develop", "HEAD", "latest"):
            errors.append(f"{rel_path}: uses {ref!r} — must pin to @vN or SHA, not @{tag}")
    return errors


def _validate_no_hardcoded_secrets(content: str, rel_path: str) -> list[str]:
    errors: list[str] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if "${{" in line and "secrets." in line:
            continue
        if "secrets." in line and "documentation" in line.lower():
            continue
        for pattern in HARDCODED_SECRET_PATTERNS:
            if pattern.search(line):
                errors.append(
                    f"{rel_path}:{line_no} possible hardcoded secret — use GitHub Encrypted Secrets"
                )
                break
    return errors


def verify_workflows(root: Path | None = None) -> tuple[list[str], list[str]]:
    root = root or _project_root()
    errors: list[str] = []
    notes: list[str] = []

    files = _workflow_files(root)
    if not files:
        errors.append(".github/workflows: no workflow files found")
        return errors, notes

    all_actions: set[str] = set()
    for path in files:
        rel = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8")
        errors.extend(_validate_no_hardcoded_secrets(content, rel))
        for match in USES_LINE.finditer(content):
            ref = match.group("ref")
            errors.extend(_validate_uses(ref, rel_path=rel, line_hint=ref))
            if ref.startswith(ALLOWED_ACTION_PREFIX):
                all_actions.add(ref)

    notes.append(f"workflows scanned: {len(files)}")
    notes.append(f"Verified Creator actions pinned: {', '.join(sorted(all_actions))}")
    return errors, notes


def main(argv: list[str] | None = None) -> int:
    _ = argv
    print("[INFO] GitHub Actions security verification (C-zone)")
    errors, notes = verify_workflows()
    for note in notes:
        print(f"  [OK] {note}")
    if errors:
        for msg in errors:
            print(f"  [FAIL] {msg}", file=sys.stderr)
        print("[FAIL] GitHub Actions security verification failed", file=sys.stderr)
        return 1
    print("[OK] GitHub Actions security verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
