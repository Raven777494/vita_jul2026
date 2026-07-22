# PersonalityModule/version.py
# 版本鎖：單一來源（與 VERSION 檔對齊）

from __future__ import annotations

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
_FALLBACK = "9.0.0"


def get_module_version() -> str:
    try:
        text = _VERSION_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text.splitlines()[0].strip()
    except OSError:
        pass
    return _FALLBACK


MODULE_VERSION = get_module_version()

# 子系統 schema 版本（契約可觀測；與模組版號分離）
DRIVE_SCHEMA_VERSION = "1.0.0"
RELATIONAL_BRIDGE_VERSION = "1.0.0"
DISPOSITION_SCHEMA_VERSION = "1.0.0"
GRAPH_CONTRACT_VERSION = "0.3.1"
