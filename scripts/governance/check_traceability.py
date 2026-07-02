#!/usr/bin/env python3
"""Verify requirements traceability matrix matches crisis scenarios and repo paths (P3-2).

Checks:
  1. Every SC-* in tests/clinical/crisis_scenarios.py appears in the Active matrix.
  2. Every Active SC-* row has a matching crisis scenario definition.
  3. Required non-SC IDs (US-*, MET-*, SEC-*, P0-*) are present in Active matrix.
  4. Code and test path columns reference existing files (or registered CI aliases).

Exit 0 if OK, 1 on failure.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = PROJECT_ROOT / "docs" / "requirements" / "traceability-matrix.md"

ACTIVE_HEADER = "## Active requirements"
PLANNED_HEADER = "## Planned"

REQUIRED_ACTIVE_IDS = frozenset(
    {
        "US-1",
        "US-2",
        "US-3",
        "US-4",
        "P0-1",
        "P0-2",
        "P0-3",
        "MET-1",
        "SEC-1",
        "SEC-2",
    }
)

# Test column aliases -> repo-relative paths
TEST_ALIASES: dict[str, str] = {
    "ci:dependency-audit": ".github/workflows/ci.yml",
    "ci:test-and-alignment": ".github/workflows/ci.yml",
    "alignment_checker": "app/tests/system_alignment_checker.py",
}

PATH_TOKEN_RE = re.compile(r"`([^`]+)`")
SC_ID_RE = re.compile(r"^SC-\d{3}$")
SCENARIO_ID_IN_SOURCE_RE = re.compile(r'scenario_id\s*=\s*["\'](SC-\d{3})["\']')


@dataclass(frozen=True)
class MatrixRow:
    req_id: str
    req_type: str
    summary: str
    code_refs: str
    test_refs: str


def _load_crisis_scenario_ids() -> frozenset[str]:
    source_path = PROJECT_ROOT / "tests" / "clinical" / "crisis_scenarios.py"
    text = source_path.read_text(encoding="utf-8")
    ids = frozenset(SCENARIO_ID_IN_SOURCE_RE.findall(text))
    if not ids:
        raise RuntimeError(f"No SC-* scenario_id values found in {source_path}")
    return ids


def _split_sections(text: str) -> tuple[str, str]:
    if ACTIVE_HEADER not in text:
        raise ValueError(f"Missing section header: {ACTIVE_HEADER}")
    active_part = text.split(ACTIVE_HEADER, 1)[1]
    if PLANNED_HEADER in active_part:
        active_body, _planned = active_part.split(PLANNED_HEADER, 1)
    else:
        active_body = active_part
    return active_body, ""


def _parse_table_rows(section_text: str) -> list[MatrixRow]:
    rows: list[MatrixRow] = []
    for line in section_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        req_id = cells[0]
        if req_id in ("ID", "---", "----") or req_id.startswith("-"):
            continue
        rows.append(
            MatrixRow(
                req_id=req_id,
                req_type=cells[1],
                summary=cells[2],
                code_refs=cells[3],
                test_refs=cells[4],
            )
        )
    return rows


def _extract_path_tokens(field: str) -> list[str]:
    tokens = PATH_TOKEN_RE.findall(field)
    if tokens:
        return tokens
    stripped = field.strip()
    if not stripped or stripped.lower() in {"n/a", "manual", "tbd"}:
        return []
    return [stripped]


def _resolve_repo_path(token: str) -> Path:
    normalized = token.replace("\\", "/").strip()
    lower = normalized.lower()
    if lower in TEST_ALIASES:
        return PROJECT_ROOT / TEST_ALIASES[lower]
    if lower.startswith("ci:"):
        alias = TEST_ALIASES.get(lower)
        if alias:
            return PROJECT_ROOT / alias
    if normalized == "alignment_checker":
        return PROJECT_ROOT / TEST_ALIASES["alignment_checker"]
    if normalized.startswith("tests/") or normalized.startswith("app/") or normalized.startswith("scripts/"):
        return PROJECT_ROOT / normalized
    if normalized.startswith(".github/"):
        return PROJECT_ROOT / normalized
    if "/" not in normalized and normalized.endswith(".py"):
        for prefix in ("app/", "tests/", "scripts/"):
            candidate = PROJECT_ROOT / prefix / normalized
            if candidate.is_file():
                return candidate
        return PROJECT_ROOT / "app" / normalized
    return PROJECT_ROOT / normalized


def _validate_paths(field: str, *, kind: str, req_id: str) -> list[str]:
    errors: list[str] = []
    tokens = _extract_path_tokens(field)
    if not tokens:
        errors.append(f"{req_id}: missing {kind} path reference")
        return errors
    for token in tokens:
        if token.lower() in {"manual", "tbd", "future sc"}:
            errors.append(f"{req_id}: {kind} still marked manual/TBD: {token!r}")
            continue
        path = _resolve_repo_path(token)
        if not path.is_file():
            errors.append(f"{req_id}: {kind} path not found: {token} -> {path.relative_to(PROJECT_ROOT)}")
    return errors


def check_traceability(matrix_path: Path) -> list[str]:
    errors: list[str] = []
    if not matrix_path.is_file():
        return [f"Matrix file missing: {matrix_path.relative_to(PROJECT_ROOT)}"]

    text = matrix_path.read_text(encoding="utf-8")
    try:
        active_section, _ = _split_sections(text)
    except ValueError as exc:
        return [str(exc)]

    rows = _parse_table_rows(active_section)
    active_ids = {row.req_id for row in rows}
    active_sc_ids = {row.req_id for row in rows if SC_ID_RE.match(row.req_id)}

    try:
        scenario_ids = _load_crisis_scenario_ids()
    except Exception as exc:
        return [f"Failed to load crisis scenarios: {exc}"]

    missing_in_matrix = sorted(scenario_ids - active_sc_ids)
    if missing_in_matrix:
        errors.append(
            "Crisis scenarios missing from Active matrix: " + ", ".join(missing_in_matrix)
        )

    orphan_matrix_sc = sorted(active_sc_ids - scenario_ids)
    if orphan_matrix_sc:
        errors.append(
            "Active matrix SC IDs without crisis_scenarios definition: "
            + ", ".join(orphan_matrix_sc)
        )

    missing_required = sorted(REQUIRED_ACTIVE_IDS - active_ids)
    if missing_required:
        errors.append("Required Active IDs missing from matrix: " + ", ".join(missing_required))

    for row in rows:
        if row.req_id.startswith("SC-") or row.req_id.startswith("US-"):
            errors.extend(_validate_paths(row.code_refs, kind="code", req_id=row.req_id))
            errors.extend(_validate_paths(row.test_refs, kind="test", req_id=row.req_id))
        elif row.req_id.startswith(("MET-", "SEC-", "P0-")):
            errors.extend(_validate_paths(row.code_refs, kind="code", req_id=row.req_id))
            errors.extend(_validate_paths(row.test_refs, kind="test", req_id=row.req_id))

    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check PRD traceability matrix")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX,
        help="Path to traceability-matrix.md",
    )
    args = parser.parse_args(argv)

    errors = check_traceability(args.matrix)
    if errors:
        print("[FAIL] Traceability check failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    scenario_count = len(_load_crisis_scenario_ids())
    print(
        f"[OK] Traceability matrix aligned "
        f"({scenario_count} SC scenarios, required IDs present, paths verified)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
