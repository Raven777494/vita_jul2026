#!/usr/bin/env python3
"""Apply GitHub branch protection for main and develop (go-live 0.2 / C1).

Uses authenticated `gh` CLI. Does not modify secrets or workflow files.

Security alignment:
  - Required status checks: CI job ids from .github/workflows/ci.yml
  - Force push / deletion disabled
  - Solo maintainer default: required_approving_review_count=0 (document in BP-RECORD)

Usage:
    python scripts/governance/apply_branch_protection.py --dry-run
    python scripts/governance/apply_branch_protection.py
    python scripts/governance/apply_branch_protection.py --require-one-approval
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_CHECKS = ("test-and-alignment", "dependency-audit")
PROTECTED_BRANCHES = ("main", "develop")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def protection_payload(*, solo: bool) -> dict[str, Any]:
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": list(REQUIRED_CHECKS),
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 0 if solo else 1,
        },
        "restrictions": None,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
    }


def apply_branch_protection(
    *,
    repo: str,
    solo: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    if not dry_run and not shutil.which("gh"):
        return {"ok": False, "error": "gh CLI not found on PATH"}, 2

    payload = protection_payload(solo=solo)
    results: dict[str, Any] = {
        "repo": repo,
        "solo": solo,
        "dry_run": dry_run,
        "required_checks": list(REQUIRED_CHECKS),
        "branches": {},
    }

    for branch in PROTECTED_BRANCHES:
        if dry_run:
            results["branches"][branch] = {"ok": True, "dry_run": True}
            continue

        proc = subprocess.run(
            [
                "gh",
                "api",
                "-X",
                "PUT",
                f"repos/{repo}/branches/{branch}/protection",
                "--input",
                "-",
            ],
            input=json.dumps(payload),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            results["branches"][branch] = {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "").strip(),
            }
        else:
            try:
                resp = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError:
                resp = {}
            results["branches"][branch] = {
                "ok": True,
                "response_keys": sorted(resp.keys()),
            }

    ok = all(v.get("ok") for v in results["branches"].values())
    results["ok"] = ok
    return results, 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(description="Apply GitHub branch protection (C1 / 0.2)")
    parser.add_argument("--repo", default="Raven777494/vita_jul2026")
    parser.add_argument(
        "--require-one-approval",
        action="store_true",
        help="Require 1 PR approval (default for solo is 0)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    solo = not args.require_one_approval
    results, code = apply_branch_protection(
        repo=args.repo,
        solo=solo,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return code

    print("[INFO] Apply branch protection (go-live 0.2 / C1)")
    if results.get("error"):
        print(f"  [FAIL] {results['error']}", file=sys.stderr)
        return code
    print(f"  [INFO] repo: {results['repo']}")
    print(f"  [INFO] approving_review_count: {0 if results['solo'] else 1}")
    print(f"  [INFO] required checks: {', '.join(results['required_checks'])}")
    if args.dry_run:
        print("  [INFO] dry-run only — no API writes")
    for branch, info in results["branches"].items():
        tag = "OK" if info.get("ok") else "FAIL"
        print(f"  [{tag}] {branch}")
        if info.get("error"):
            print(f"         {info['error']}")
    if results.get("ok"):
        print("[OK] Branch protection apply finished")
    else:
        print("[FAIL] Branch protection apply failed", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
