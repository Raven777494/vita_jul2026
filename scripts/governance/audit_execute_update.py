#!/usr/bin/env python3
"""Audit execute_update call sites (P5-3 / TD-003).

Verifies that all repository callers of execute_update are known and that
DatabaseManager.execute_update raises DatabaseUpdateError on failure instead
of silently returning 0.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CallSite:
    path: str
    line: int


# Known call sites after P5-3 audit (definition excluded).
ALLOWED_CALL_SITES: frozenset[str] = frozenset(
    {
        "app/services/db_manager.py",
        "scripts/db/retention_batch.py",
    }
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def find_execute_update_calls(root: Path | None = None) -> list[CallSite]:
    """Return execute_update( call sites outside the method definition."""
    root = root or _project_root()
    sites: list[CallSite] = []
    skip_dirs = {
        ".git",
        ".engine7b",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "tests",
    }

    for path in root.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        rel = _normalize_path(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "execute_update":
                if isinstance(func.value, ast.Name) and func.value.id == "self":
                    continue
                sites.append(CallSite(rel, node.lineno))
            elif isinstance(func, ast.Name) and func.id == "execute_update":
                sites.append(CallSite(rel, node.lineno))

    return sorted(sites, key=lambda s: (s.path, s.line))


def audit_execute_update(root: Path | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    root = root or _project_root()
    errors: list[str] = []
    warnings: list[str] = []

    sites = find_execute_update_calls(root)
    unknown = [s for s in sites if s.path not in ALLOWED_CALL_SITES]
    if unknown:
        for site in unknown:
            errors.append(
                f"Unexpected execute_update caller: {site.path}:{site.line} "
                f"(add to ALLOWED_CALL_SITES after review)"
            )

    db_manager_path = root / "app" / "services" / "db_manager.py"
    source = db_manager_path.read_text(encoding="utf-8")
    if "raise DatabaseUpdateError" not in source:
        errors.append(
            "app/services/db_manager.py: execute_update must raise DatabaseUpdateError"
        )
    if "return 0" in source.split("def execute_update", 1)[-1].split("\n    def ", 1)[0]:
        errors.append(
            "app/services/db_manager.py: execute_update must not return 0 on failure"
        )

    allowed_without_sites = ALLOWED_CALL_SITES - {s.path for s in sites} - {
        "app/services/db_manager.py"
    }
    for path in sorted(allowed_without_sites):
        warnings.append(f"Allowlisted path has no execute_update calls: {path}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    errors, warnings = audit_execute_update(root)

    print("[INFO] execute_update audit (P5-3 / TD-003)")
    sites = find_execute_update_calls(root)
    for site in sites:
        tag = "OK" if site.path in ALLOWED_CALL_SITES else "FAIL"
        print(f"  [{tag}] {site.path}:{site.line}")

    for msg in warnings:
        print(f"[WARN] {msg}", file=sys.stderr)

    if errors:
        for msg in errors:
            print(f"[FAIL] {msg}", file=sys.stderr)
        print("[FAIL] execute_update audit failed", file=sys.stderr)
        return 1

    print("[OK] execute_update audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
