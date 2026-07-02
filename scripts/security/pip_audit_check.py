#!/usr/bin/env python3
"""Run pip-audit against requirements.txt (CI and local security gate).

Uses pip-audit as a Python CLI — no third-party GitHub Actions required.
Install: pip install pip-audit==2.7.3
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _audit_requirements_file(requirements_path: Path) -> Path:
    """Build ASCII-only requirements (no comments) for pip-audit portability."""
    package_lines: list[str] = []
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        package_lines.append(stripped)

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="ascii",
        suffix="-requirements.txt",
        delete=False,
    )
    handle.write("\n".join(package_lines) + "\n")
    handle.close()
    return Path(handle.name)


def run_pip_audit(requirements_path: Path, strict: bool) -> int:
    if not requirements_path.is_file():
        print(f"[FAIL] requirements file not found: {requirements_path}")
        return 1

    audit_path = _audit_requirements_file(requirements_path)

    cmd = [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        str(audit_path),
        "--format",
        "columns",
    ]
    if strict:
        cmd.append("--strict")

    print(f"[INFO] Running: {' '.join(cmd)}")
    try:
        completed = subprocess.run(cmd, check=False)
    finally:
        try:
            audit_path.unlink(missing_ok=True)
        except OSError:
            pass

    if completed.returncode == 0:
        print("[OK] pip-audit: no known vulnerabilities reported")
    else:
        print(
            "[FAIL] pip-audit reported vulnerabilities or audit failure. "
            "See output above; update pinned dependencies or document exception in "
            "docs/security/dependency-scanning.md"
        )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="VITA dependency vulnerability scan")
    parser.add_argument(
        "--requirements",
        type=Path,
        default=_project_root() / "requirements-audit.txt",
        help="Path to auditable requirements file (default: requirements-audit.txt)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable pip-audit strict mode (fail on unpinned requirements)",
    )
    args = parser.parse_args()
    return run_pip_audit(args.requirements, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
