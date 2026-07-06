#!/usr/bin/env python3
"""Verify P6-2 requirements final sign-off deliverables (Governance #1).

Checks:
  - PRD.md Approved v1.0 (not engineering-baseline-only)
  - companion-language-guide v1.0 with forbidden-pattern freeze policy
  - prd-v1-clinical-approval-checklist.md present
  - CD-002 closed in tech-debt-register
  - Traceability checker passes (SC-001..010)

Usage:
    python scripts/governance/verify_p6_requirements_signoff.py
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


def verify_prd(content: str) -> list[str]:
    errors: list[str] = []
    if "Approved v1.0" not in content:
        errors.append("PRD.md: missing 'Approved v1.0' status")
    if "engineering baseline" in content.lower():
        errors.append("PRD.md: still contains 'engineering baseline' wording")
    for token in ("SC-006", "SC-010", "prd-v1-clinical-approval-checklist"):
        if token not in content:
            errors.append(f"PRD.md: missing '{token}'")
    return errors


def verify_companion_guide(content: str) -> list[str]:
    errors: list[str] = []
    required = (
        "Version: 1.0 (P6-2)",
        "frozen baseline",
        "Version policy and change control",
        "FORBIDDEN_PATTERNS",
        "ADR",
        "clinical-signoff-template.md",
    )
    for token in required:
        if token not in content:
            errors.append(f"companion-language-guide.md: missing '{token}'")
    return errors


def verify_register(content: str) -> list[str]:
    errors: list[str] = []
    if "CD-002" not in content or "Closed P6-2" not in content:
        errors.append("tech-debt-register: CD-002 not marked Closed P6-2")
    return errors


def verify_p6_requirements_signoff(root: Path | None = None) -> list[str]:
    root = root or _project_root()
    errors: list[str] = []

    checklist = root / "docs" / "governance" / "prd-v1-clinical-approval-checklist.md"
    if not checklist.is_file():
        errors.append("missing docs/governance/prd-v1-clinical-approval-checklist.md")

    try:
        errors.extend(verify_prd(_read(root, "docs/requirements/PRD.md")))
        errors.extend(
            verify_companion_guide(_read(root, "docs/clinical/companion-language-guide.md"))
        )
        errors.extend(verify_register(_read(root, "docs/governance/tech-debt-register.md")))
    except FileNotFoundError as exc:
        errors.append(str(exc))

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.governance.check_traceability import check_traceability

    matrix = root / "docs" / "requirements" / "traceability-matrix.md"
    trace_errors = check_traceability(matrix)
    if trace_errors:
        errors.append(f"traceability: {'; '.join(trace_errors[:3])}")
        if len(trace_errors) > 3:
            errors.append(f"traceability: ... and {len(trace_errors) - 3} more")

    return errors


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    print("[INFO] P6-2 requirements sign-off verification")
    errors = verify_p6_requirements_signoff(root)

    for label, rel in (
        ("PRD Approved v1.0", "docs/requirements/PRD.md"),
        ("companion guide v1.0 freeze", "docs/clinical/companion-language-guide.md"),
        ("PRD approval checklist", "docs/governance/prd-v1-clinical-approval-checklist.md"),
    ):
        ok = (root / rel).is_file() and not any(rel in e for e in errors)
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")

    if not any("traceability" in e for e in errors):
        print("  [OK] traceability matrix (SC-001..010)")

    if errors:
        for msg in errors:
            print(f"  [FAIL] {msg}", file=sys.stderr)
        print("[FAIL] P6-2 requirements sign-off verification failed", file=sys.stderr)
        return 1

    print("[OK] P6-2 requirements sign-off verification passed")
    print(
        "[INFO] Complete external prd-v1-clinical-approval-checklist before production"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
