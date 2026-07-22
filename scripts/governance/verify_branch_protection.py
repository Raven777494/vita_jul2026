#!/usr/bin/env python3
"""Verify GitHub branch protection for main and develop (go-live 0.2 / C1).

Reads protection via authenticated `gh` API. Never prints secrets.

Usage:
    python scripts/governance/verify_branch_protection.py
    python scripts/governance/verify_branch_protection.py --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_CHECKS = frozenset({"test-and-alignment", "dependency-audit"})
PROTECTED_BRANCHES = ("main", "develop")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _gh_api(path: str) -> tuple[dict[str, Any] | None, int, str | None]:
    if not shutil.which("gh"):
        return None, 2, "gh CLI not found on PATH"
    proc = subprocess.run(
        ["gh", "api", path],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return None, 1, err or f"gh exited {proc.returncode}"
    try:
        return json.loads(proc.stdout or "{}"), 0, None
    except json.JSONDecodeError as exc:
        return None, 1, f"invalid JSON: {exc}"


def _contexts_from_protection(data: dict[str, Any]) -> set[str]:
    checks = data.get("required_status_checks") or {}
    contexts = set(checks.get("contexts") or [])
    # Newer API may use checks[].context
    for item in checks.get("checks") or []:
        ctx = item.get("context")
        if ctx:
            contexts.add(str(ctx))
    return contexts


def verify_branch_protection(*, repo: str) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {
        "repo": repo,
        "required_checks": sorted(REQUIRED_CHECKS),
        "branches": {},
        "ok": True,
    }
    overall_code = 0

    for branch in PROTECTED_BRANCHES:
        data, code, err = _gh_api(f"repos/{repo}/branches/{branch}/protection")
        entry: dict[str, Any] = {"branch": branch}
        if data is None:
            entry["ok"] = False
            entry["error"] = err
            # 404 Branch not protected
            if err and "not protected" in err.lower():
                entry["protected"] = False
            result["branches"][branch] = entry
            result["ok"] = False
            overall_code = max(overall_code, code if code else 1)
            continue

        contexts = _contexts_from_protection(data)
        missing = sorted(REQUIRED_CHECKS - contexts)
        pr = data.get("required_pull_request_reviews") or {}
        enforce_admins = bool((data.get("enforce_admins") or {}).get("enabled"))
        allow_force = bool((data.get("allow_force_pushes") or {}).get("enabled"))
        allow_delete = bool((data.get("allow_deletions") or {}).get("enabled"))
        conversation = bool(
            (data.get("required_conversation_resolution") or {}).get("enabled")
        )
        strict = bool((data.get("required_status_checks") or {}).get("strict"))

        problems: list[str] = []
        if missing:
            problems.append(f"missing status checks: {', '.join(missing)}")
        if not strict:
            problems.append("required_status_checks.strict is false")
        if allow_force:
            problems.append("allow_force_pushes must be false")
        if allow_delete:
            problems.append("allow_deletions must be false")
        if not conversation:
            problems.append("required_conversation_resolution should be true")
        if pr.get("dismiss_stale_reviews") is False:
            problems.append("dismiss_stale_reviews should be true")

        entry.update(
            {
                "ok": not problems,
                "protected": True,
                "contexts": sorted(contexts),
                "missing_checks": missing,
                "enforce_admins": enforce_admins,
                "allow_force_pushes": allow_force,
                "allow_deletions": allow_delete,
                "required_conversation_resolution": conversation,
                "required_approving_review_count": pr.get(
                    "required_approving_review_count"
                ),
                "problems": problems,
            }
        )
        if problems:
            result["ok"] = False
            overall_code = 1
        result["branches"][branch] = entry

    return result, overall_code


def main(argv: list[str] | None = None) -> int:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(description="Verify GitHub branch protection (0.2)")
    parser.add_argument("--repo", default="Raven777494/vita_jul2026")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload, code = verify_branch_protection(repo=args.repo)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("[INFO] Branch protection verification (go-live 0.2)")
        print(f"  [INFO] repo: {payload['repo']}")
        print(f"  [INFO] required checks: {', '.join(payload['required_checks'])}")
        for branch, info in payload["branches"].items():
            tag = "OK" if info.get("ok") else "FAIL"
            print(f"  [{tag}] {branch}")
            if info.get("error"):
                print(f"         {info['error']}")
            for problem in info.get("problems") or []:
                print(f"         - {problem}")
            if info.get("ok"):
                print(
                    f"         checks={info.get('contexts')} "
                    f"approvals={info.get('required_approving_review_count')} "
                    f"enforce_admins={info.get('enforce_admins')}"
                )
        if payload["ok"]:
            print("[OK] Branch protection verification passed")
        else:
            print("[FAIL] Branch protection verification failed", file=sys.stderr)
            print(
                "[INFO] Apply with: python scripts/governance/apply_branch_protection.py"
            )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
