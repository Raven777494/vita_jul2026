"""Tests for ADR-002 memory model alignment (P4-4)."""

from __future__ import annotations

from pathlib import Path

from app.governance.memory_model_alignment import (
    ADR002_REL,
    scan_for_forbidden_age_writes,
    verify_memory_model_alignment,
)


def test_adr002_file_exists():
    root = Path(__file__).resolve().parents[2]
    assert (root / ADR002_REL).is_file()


def test_verify_memory_model_alignment_passes_on_repo():
    report = verify_memory_model_alignment()
    assert report.ok, report.issues
    assert any("ADR-002 present" in item for item in report.checked)
    assert any("No runtime AGE" in item for item in report.checked)


def test_scan_flags_forbidden_cypher_in_synthetic_file(tmp_path):
    app_dir = tmp_path / "app" / "fake"
    app_dir.mkdir(parents=True)
    bad_file = app_dir / "bad_module.py"
    bad_file.write_text("def run():\n    db.execute(cypher('vita_memory_graph', $$ MATCH (n) RETURN n $$))\n")
    issues = scan_for_forbidden_age_writes(tmp_path, self_path=tmp_path / "skip.py")
    assert any("bad_module.py" in issue for issue in issues)
    assert any("cypher" in issue for issue in issues)


def test_scan_allows_db_manager_provision_allowlist():
    root = Path(__file__).resolve().parents[2]
    issues = scan_for_forbidden_age_writes(root)
    assert not any("db_manager.py" in i and "create_graph" in i for i in issues)
