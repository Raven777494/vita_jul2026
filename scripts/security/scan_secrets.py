#!/usr/bin/env python3
"""Scan tracked or staged files for accidental secret literals (P3-1).

Exit 0 if clean, 1 if potential secrets found.
Does not print matched secret values (only file and rule id).

Usage:
  python scripts/security/scan_secrets.py
  python scripts/security/scan_secrets.py --paths file1 file2
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Paths allowed to contain placeholder / CI-only credentials
ALLOWLIST_PATHS = frozenset(
    {
        "config/.env.compose.example",
        "config/.env.compose.ci",
        "config/.env.example",
        "tests/platform/test_compose_env.py",
        "scripts/security/scan_secrets.py",
    }
)

# File suffixes to scan
SCAN_SUFFIXES = frozenset(
    {
        ".py",
        ".yml",
        ".yaml",
        ".json",
        ".env",
        ".example",
        ".ci",
        ".sh",
        ".bat",
        ".md",
        ".toml",
        ".ini",
    }
)

SKIP_DIRS = frozenset(
    {
        ".git",
        ".engine7b",
        "node_modules",
        "llama-cpp-python",
        "models",
        "cache",
        "data",
        "logs",
        "htmlcov",
        ".pytest_cache",
        "__pycache__",
    }
)

RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "AWS_ACCESS_KEY",
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ),
    (
        "GITHUB_TOKEN",
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    ),
    (
        "PRIVATE_KEY_BLOCK",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "HARDCODED_POSTGRES_PASSWORD",
        re.compile(
            r'POSTGRES_PASSWORD:\s*["\']?(?!(\$\{|change_me|ci_compose|\$\{POSTGRES_PASSWORD))[^"\'\s${:?][^"\']*["\']?',
            re.IGNORECASE,
        ),
    ),
    (
        "HARDCODED_JWT_IN_COMPOSE",
        re.compile(
            r'JWT_SECRET:\s*["\']?(?!(\$\{|change_me|ci_jwt|\$\{JWT_SECRET))[^"\'\s${:?][^"\']*["\']?',
            re.IGNORECASE,
        ),
    ),
    (
        "DATABASE_URL_WITH_EMBEDDED_PASSWORD",
        re.compile(
            r"postgresql(?:\+[\w]+)?://[^:]+:(?!change_me|ci_compose|\$\{)[^@\s/]{8,}@",
            re.IGNORECASE,
        ),
    ),
]

SKIP_LINE_PATTERNS = (
    re.compile(r"\$\{\{"),  # GitHub Actions secret refs
    re.compile(r"\$\{"),  # compose interpolation
    re.compile(r":\?\w"),  # compose required var
    re.compile(r"secrets\."),  # documentation
    re.compile(r"change_me", re.I),
    re.compile(r"ci_compose", re.I),
    re.compile(r"ci_jwt", re.I),
    re.compile(r"dev_jwt_secret", re.I),
    re.compile(r"example", re.I),
    re.compile(r"placeholder", re.I),
    re.compile(r"\{user\}|\{password\}|\{db_user\}|\{db_password\}", re.I),
    re.compile(r"\{DB_USER\}|\{DB_PASSWORD\}|\{DB_HOST\}"),
    re.compile(r"os\.getenv\("),
    re.compile(r"compose_or_env\("),
)


def _git_tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        paths.append(PROJECT_ROOT / line.replace("/", "\\") if "\\" in str(PROJECT_ROOT) else PROJECT_ROOT / line)
    return paths


def _walk_project_files() -> list[Path]:
    found: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES and path.name not in ALLOWLIST_PATHS:
            if path.name not in ("docker-compose.yml", "Dockerfile"):
                continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(".git/"):
            continue
        found.append(path)
    return found


def _should_scan(path: Path) -> bool:
    try:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return False
    if rel in ALLOWLIST_PATHS:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    name = path.name
    if name in (".env", ".env.local", ".env.compose") or name.endswith(".local"):
        return False
    if rel.startswith("config/") and name == ".env":
        return False
    suffix = path.suffix.lower()
    if suffix in SCAN_SUFFIXES or name in ("docker-compose.yml", "Dockerfile"):
        return True
    return False


def _line_skippable(line: str) -> bool:
    return any(p.search(line) for p in SKIP_LINE_PATTERNS)


def scan_file(path: Path) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _line_skippable(line):
            continue
        for rule_id, pattern in RULES:
            if pattern.search(line):
                hits.append((rel, line_no, rule_id))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for accidental secrets in repo files")
    parser.add_argument("--paths", nargs="*", help="Specific files to scan (default: git ls-files or walk)")
    args = parser.parse_args()

    if args.paths:
        files = [Path(p) for p in args.paths]
    else:
        files = _git_tracked_files()
        if not files:
            files = [p for p in _walk_project_files() if _should_scan(p)]

    all_hits: list[tuple[str, int, str]] = []
    for path in files:
        if not path.is_file() or not _should_scan(path):
            continue
        all_hits.extend(scan_file(path))

    if all_hits:
        print("[FAIL] Potential secrets detected:", file=sys.stderr)
        for rel, line_no, rule_id in all_hits:
            print(f"  {rel}:{line_no} [{rule_id}]", file=sys.stderr)
        print(
            "[FAIL] Remove literals or add safe placeholder / compose ${VAR} interpolation.",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] Secret scan clean ({len(files)} files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
