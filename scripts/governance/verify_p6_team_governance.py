#!/usr/bin/env python3
"""Verify P6-1 team collaboration deliverables (Governance #11).

Checks:
  - clinical-signoff-template.md present with SC checklist
  - RACI.md v1.0 with external roster policy
  - PR template requires clinical sign-off for app/clinical and tests/clinical

Usage:
    python scripts/governance/verify_p6_team_governance.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    return path.read_text(encoding="utf-8")


def verify_clinical_signoff_template(content: str) -> list[str]:
    errors: list[str] = []
    required = (
        "Version: 1.0 (P6-1)",
        "SC-001",
        "SC-010",
        "Forbidden-pattern checklist",
        "CLIN-SIGN-",
    )
    for token in required:
        if token not in content:
            errors.append(f"clinical-signoff-template.md: missing '{token}'")
    return errors


def verify_raci(content: str) -> list[str]:
    errors: list[str] = []
    required = (
        "Version: 1.0 (P6-1)",
        "Clinical advisor",
        "External roster",
        "clinical-signoff-template.md",
        "verify_p6_team_governance.py",
    )
    for token in required:
        if token not in content:
            errors.append(f"RACI.md: missing '{token}'")
    if "**A**" not in content:
        errors.append("RACI.md: missing accountability markers")
    return errors


def verify_pr_template(content: str) -> list[str]:
    errors: list[str] = []
    required = (
        "Clinical advisor sign-off",
        "app/clinical/",
        "tests/clinical/",
        "clinical-signoff-template.md",
        "CLIN-SIGN-",
    )
    for token in required:
        if token not in content:
            errors.append(f"PULL_REQUEST_TEMPLATE.md: missing '{token}'")
    return errors


def verify_p6_team_governance(root: Path | None = None) -> list[str]:
    root = root or _project_root()
    errors: list[str] = []
    try:
        errors.extend(verify_clinical_signoff_template(
            _read(root, "docs/governance/clinical-signoff-template.md")
        ))
        errors.extend(verify_raci(_read(root, "docs/governance/RACI.md")))
        errors.extend(verify_pr_template(
            _read(root, ".github/PULL_REQUEST_TEMPLATE.md")
        ))
    except FileNotFoundError as exc:
        errors.append(str(exc))
    return errors


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    print("[INFO] P6-1 team collaboration verification")
    errors = verify_p6_team_governance(root)

    checks = [
        ("clinical-signoff-template.md", "docs/governance/clinical-signoff-template.md"),
        ("RACI.md v1.0", "docs/governance/RACI.md"),
        ("PR template clinical sign-off", ".github/PULL_REQUEST_TEMPLATE.md"),
    ]
    for label, rel in checks:
        ok = (root / rel).is_file() and not any(rel in e for e in errors)
        tag = "OK" if ok else "FAIL"
        print(f"  [{tag}] {label}")

    if errors:
        for msg in errors:
            print(f"  [FAIL] {msg}", file=sys.stderr)
        print("[FAIL] P6-1 team collaboration verification failed", file=sys.stderr)
        return 1

    print("[OK] P6-1 team collaboration verification passed")
    print(
        "[INFO] P6-1.4 (production release sign-off archive) is external — "
        "complete before go-live"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
