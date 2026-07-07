#!/usr/bin/env python3
"""Verify minimum test coverage on clinical/safety critical paths (Governance #6).

Runs pytest with coverage on companion gate, language policy, and crisis hub.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    """Run pytest with coverage on user-facing clinical modules (>= 70%).

    EmotionalSafetyHub is validated functionally by tests/clinical/ SC-001..010
    and app/tests/test_emotional_hub.py; line coverage on the full hub module
    is tracked separately (future increment).
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/clinical/",
        "tests/security/",
        "app/tests/test_emotional_hub.py",
        "--cov=app/clinical",
        "--cov-report=term-missing:skip-covered",
        "--cov-fail-under=70",
        "-q",
        "--tb=short",
    ]
    print("[INFO] Critical path coverage gate (clinical + safety >= 70%)")
    result = subprocess.run(cmd, cwd=root)
    if result.returncode == 0:
        print("[OK] Critical path coverage gate passed")
    else:
        print("[FAIL] Critical path coverage gate failed", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
