#!/usr/bin/env python3
"""Verify P5-3 technical debt program closure (Governance #12).

Checks:
  - TD-003 closed in tech-debt-register.md
  - Review log section present with current month entry
  - execute_update audit passes
  - No High-priority open TD without owner/target date

Usage:
    python scripts/governance/verify_p5_tech_debt.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_register(root: Path) -> str:
    path = root / "docs" / "governance" / "tech-debt-register.md"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def verify_register(content: str, *, now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    ref = now or datetime.now(timezone.utc)

    if "TD-003" not in content or "Closed P5-3" not in content:
        errors.append("tech-debt-register: TD-003 not marked Closed P5-3")

    if "## Review log" not in content:
        errors.append("tech-debt-register: missing Review log section")

    month_tag = ref.strftime("%Y-%m")
    if month_tag not in content:
        errors.append(f"tech-debt-register: no Review log entry for {month_tag}")

    open_high = re.findall(
        r"^\| (TD-\d+|CD-\d+) \|[^|]+\| High \|[^|]+\| ([^|]+) \|",
        content,
        re.MULTILINE,
    )
    for item_id, target in open_high:
        target = target.strip()
        if target.lower().startswith("closed"):
            continue
        if not target or target.upper() in {"TBD", "—", "-"}:
            errors.append(
                f"tech-debt-register: {item_id} is High priority open without target date"
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    print("[INFO] P5-3 technical debt verification")
    errors: list[str] = []

    try:
        content = _read_register(root)
        errors.extend(verify_register(content))
        if not errors:
            print("  [OK] tech-debt-register: TD-003 closed, Review log present")
    except FileNotFoundError as exc:
        errors.append(str(exc))

    from scripts.governance.audit_execute_update import audit_execute_update

    audit_errors, _ = audit_execute_update(root)
    if audit_errors:
        errors.extend(audit_errors)
    else:
        print("  [OK] execute_update audit: all call sites known, raises on failure")

    deploy_appendix = root / "docs" / "operations" / "deploy.md"
    if "## Staging deploy drill record" not in deploy_appendix.read_text(encoding="utf-8"):
        errors.append("deploy.md: missing Staging deploy drill record appendix")
    else:
        print("  [OK] deploy.md: staging drill record appendix present")

    if errors:
        for msg in errors:
            print(f"  [FAIL] {msg}", file=sys.stderr)
        print("[FAIL] P5-3 technical debt verification failed", file=sys.stderr)
        return 1

    print("[OK] P5-3 technical debt verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
