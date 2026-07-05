"""Memory model alignment verification (ADR-002, P4-4).

Primary application write path: relational PostgreSQL
  - gsw_eternal_echoes (pgvector HNSW) for semantic recall
  - memory_graph table for structured graph nodes (ORM ready)

Apache AGE graph vita_memory_graph is provisioned as read-only infrastructure
reserve; no runtime cypher writes in application code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ADR002_REL = "docs/architecture/adr-002-memory-model.md"

# Provisioning-only locations for create_graph / LOAD 'age' (not runtime writes).
AGE_PROVISION_ALLOWLIST = frozenset(
    {
        "app/services/db_manager.py",
        "init-db/01-extensions.sql",
        "init-db/03-age-graph.sql",
    }
)

# Scan these trees for forbidden runtime AGE write patterns.
RUNTIME_SCAN_DIRS = ("app", "PersonalityModule")

FORBIDDEN_RUNTIME_PATTERNS: Sequence[str] = (
    "cypher(",
    "cypher('",
    'cypher("',
    ".cypher(",
    "SELECT * FROM cypher",
)

PRIMARY_PATH_MODULES = (
    "app/services/db_manager.py",
    "app/services/memory_chain_service.py",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class MemoryModelReport:
    ok: bool
    checked: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": list(self.checked),
            "issues": list(self.issues),
        }


def scan_for_forbidden_age_writes(
    root: Path,
    *,
    scan_dirs: Sequence[str] = RUNTIME_SCAN_DIRS,
    self_path: Optional[Path] = None,
) -> List[str]:
    """Return issues for runtime AGE write patterns outside the provision allowlist."""
    issues: List[str] = []
    self_rel = (
        self_path.relative_to(root).as_posix()
        if self_path is not None
        else "app/governance/memory_model_alignment.py"
    )

    for dir_name in scan_dirs:
        base = root / dir_name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel == self_rel:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                issues.append(f"{rel}: cannot read file: {exc}")
                continue

            for pattern in FORBIDDEN_RUNTIME_PATTERNS:
                if pattern in text:
                    issues.append(
                        f"{rel}: forbidden AGE runtime pattern {pattern!r} (ADR-002)"
                    )

            if "create_graph" in text and rel not in AGE_PROVISION_ALLOWLIST:
                issues.append(
                    f"{rel}: create_graph outside provision allowlist (ADR-002)"
                )

    return issues


def verify_memory_model_alignment(
    root: Optional[Path] = None,
) -> MemoryModelReport:
    """Static alignment check for ADR-002 primary path and no dual AGE writes."""
    base = root or project_root()
    checked: List[str] = []
    issues: List[str] = []

    adr_path = base / ADR002_REL
    if adr_path.is_file():
        checked.append(f"ADR-002 present: {ADR002_REL}")
    else:
        issues.append(f"Missing {ADR002_REL}")

    for rel in PRIMARY_PATH_MODULES:
        if (base / rel).is_file():
            checked.append(f"Primary path module present: {rel}")
        else:
            issues.append(f"Missing primary path module: {rel}")

    forbidden = scan_for_forbidden_age_writes(base, self_path=Path(__file__))
    if forbidden:
        issues.extend(forbidden)
    else:
        checked.append(
            "No runtime AGE cypher/create_graph writes in app/ or PersonalityModule/"
        )

    return MemoryModelReport(ok=len(issues) == 0, checked=checked, issues=issues)
