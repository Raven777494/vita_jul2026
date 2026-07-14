#!/usr/bin/env python3
"""Verify D-zone staging deploy deliverables (go-live 1.2–1.4, 2.1–2.4).

Checks repo-side contract for:
  - deploy.yml workflow_dispatch inputs and jobs
  - deploy scripts present and referenced
  - smoke / rollback / SSH deploy paths
  - D-zone runbook documents all checklist steps

Usage:
    python scripts/governance/verify_deploy_d_zone.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_SCRIPTS = (
    "scripts/deploy/smoke_check.sh",
    "scripts/deploy/rollback.sh",
    "scripts/deploy/rollback.ps1",
    "scripts/deploy/ssh_compose_deploy.sh",
    "scripts/deploy/hss_local_deploy.ps1",
    "scripts/deploy/write_compose_env.py",
    "scripts/observability/verify_p5_monitoring.py",
    "scripts/observability/record_mon_steady_state.py",
    "scripts/observability/drill_escalation_webhook.py",
)

REQUIRED_COMPOSE = (
    "docker-compose.yml",
    "docker-compose.smoke.yml",
    "config/.env.compose.ci",
)

RUNBOOK = "docs/operations/deploy-d-zone.md"
DEPLOY_WORKFLOW = ".github/workflows/deploy.yml"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    return path.read_text(encoding="utf-8")


def verify_deploy_workflow(content: str) -> list[str]:
    errors: list[str] = []
    required_snippets = (
        "workflow_dispatch:",
        "environment:",
        "dry_run:",
        "default: staging",
        "default: true",
        "build-and-smoke:",
        "deploy-host:",
        "if: inputs.dry_run == false",
        "scripts/deploy/smoke_check.sh",
        "scripts/deploy/ssh_compose_deploy.sh",
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "python-version: \"3.11\"",
    )
    for snippet in required_snippets:
        if snippet not in content:
            errors.append(f"{DEPLOY_WORKFLOW} missing required snippet: {snippet!r}")

    if "uses: actions/setup-python@v5" not in content:
        errors.append(f"{DEPLOY_WORKFLOW} must pin actions/setup-python@v5 before python steps")

    python_steps = re.findall(r"run:\s*\|\s*\n(?:.*\n)*?.*python scripts/", content)
    setup_count = content.count("uses: actions/setup-python@v5")
    if setup_count < 2:
        errors.append(
            f"{DEPLOY_WORKFLOW} expected setup-python in both jobs (found {setup_count})"
        )
    if not python_steps and "python scripts/deploy/write_compose_env.py" not in content:
        errors.append(f"{DEPLOY_WORKFLOW} missing write_compose_env.py invocation")

    return errors


def verify_ssh_compose_deploy(content: str) -> list[str]:
    errors: list[str] = []
    required = (
        "build postgres",
        "docker-compose.smoke.yml",
        "smoke_check.sh",
        "--wait",
    )
    for snippet in required:
        if snippet not in content:
            errors.append(f"ssh_compose_deploy.sh missing: {snippet!r}")
    return errors


def verify_runbook(content: str) -> list[str]:
    errors: list[str] = []
    required = (
        "D1",
        "D2",
        "D2-B",
        "D3",
        "D3-A",
        "D4",
        "D4-A",
        "1.2",
        "1.3",
        "1.4",
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "dry_run=true",
        "dry_run=false",
        "hss_local_deploy.ps1",
        "record_mon_steady_state.py",
        "rollback.sh",
        "rollback.ps1",
        "verify_p5_monitoring.py",
        "drill_escalation_webhook.py",
        "DEP-DRILL-",
    )
    for snippet in required:
        if snippet not in content:
            errors.append(f"{RUNBOOK} missing section marker: {snippet!r}")
    return errors


def verify_contract(root: Path | None = None) -> tuple[list[str], list[str]]:
    root = root or _project_root()
    errors: list[str] = []
    notes: list[str] = []

    for rel in REQUIRED_SCRIPTS + REQUIRED_COMPOSE:
        if not (root / rel).is_file():
            errors.append(f"missing required file: {rel}")
        else:
            notes.append(f"present: {rel}")

    if not (root / RUNBOOK).is_file():
        errors.append(f"missing runbook: {RUNBOOK}")
    else:
        notes.append(f"present: {RUNBOOK}")
        errors.extend(verify_runbook(_read(root, RUNBOOK)))

    if not (root / DEPLOY_WORKFLOW).is_file():
        errors.append(f"missing workflow: {DEPLOY_WORKFLOW}")
    else:
        wf = _read(root, DEPLOY_WORKFLOW)
        errors.extend(verify_deploy_workflow(wf))

    ssh = root / "scripts/deploy/ssh_compose_deploy.sh"
    if ssh.is_file():
        errors.extend(verify_ssh_compose_deploy(ssh.read_text(encoding="utf-8")))

    return errors, notes


def main(argv: list[str] | None = None) -> int:
    _ = argv
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    print("[INFO] D-zone deploy verification")
    errors, notes = verify_contract(root)
    for note in notes:
        print(f"  [OK] {note}")
    if errors:
        for msg in errors:
            print(f"  [FAIL] {msg}", file=sys.stderr)
        print("[FAIL] D-zone deploy verification failed", file=sys.stderr)
        return 1
    print("[OK] D-zone deploy verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
