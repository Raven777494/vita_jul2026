"""Version lock: PersonalityModule MODULE_VERSION matches VERSION file."""

from pathlib import Path

from PersonalityModule.version import (
    DISPOSITION_SCHEMA_VERSION,
    DRIVE_SCHEMA_VERSION,
    MODULE_VERSION,
    RELATIONAL_BRIDGE_VERSION,
    get_module_version,
)


def test_module_version_locked_to_9():
    assert MODULE_VERSION == "9.0.0"
    assert get_module_version() == "9.0.0"
    version_file = Path(__file__).resolve().parents[2] / "PersonalityModule" / "VERSION"
    assert version_file.read_text(encoding="utf-8").strip().splitlines()[0] == "9.0.0"


def test_schema_versions_present():
    assert DRIVE_SCHEMA_VERSION == "1.0.0"
    assert RELATIONAL_BRIDGE_VERSION == "1.0.0"
    assert DISPOSITION_SCHEMA_VERSION == "1.0.0"
