"""Load and apply config/hardware_profile.json — shared by Seele, app, and tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROFILE_PATH = Path(__file__).resolve().parent / "config" / "hardware_profile.json"

_COMPUTE_KEYS = ("gpu_layers", "n_threads", "n_ctx", "priority_level")
_PROFILE_MERGE_KEYS = _COMPUTE_KEYS + ("conditional",)


def profile_path() -> Path:
    return _PROFILE_PATH


def load_hardware_profile() -> Optional[Dict[str, Any]]:
    if not _PROFILE_PATH.exists():
        return None
    try:
        with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def get_service_overrides(service_name: str) -> Dict[str, Any]:
    profile = load_hardware_profile()
    if not profile:
        return {}
    return dict(profile.get("services", {}).get(service_name, {}))


def merge_service_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of a config.json service entry with hardware profile overrides."""
    name = entry.get("name", "")
    ovr = get_service_overrides(name)
    if not ovr:
        return dict(entry)
    merged = dict(entry)
    for key in _PROFILE_MERGE_KEYS:
        if key in ovr:
            merged[key] = ovr[key]
    return merged


def get_conditional_service_names(profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """Service IDs marked conditional in hardware_profile.json."""
    p = profile or load_hardware_profile() or {}
    names: List[str] = []
    for name, cfg in (p.get("services") or {}).items():
        if cfg.get("conditional"):
            names.append(name)
    return names


def get_resident_service_names(profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """Always-on services (not conditional)."""
    p = profile or load_hardware_profile() or {}
    names: List[str] = []
    for name, cfg in (p.get("services") or {}).items():
        if not cfg.get("conditional"):
            names.append(name)
    return names


def merge_config_services(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [merge_service_entry(s) for s in services]


def vram_reserve_mb(profile: Optional[Dict[str, Any]] = None) -> int:
    p = profile or load_hardware_profile() or {}
    total = int(p.get("vram_total_mb", 16384))
    pct = int(p.get("vram_reserve_percent", 20))
    return int(total * pct / 100)


def vram_budget_mb(profile: Optional[Dict[str, Any]] = None) -> int:
    p = profile or load_hardware_profile() or {}
    if "vram_budget_mb" in p:
        return int(p["vram_budget_mb"])
    total = int(p.get("vram_total_mb", 16384))
    return total - vram_reserve_mb(p)


def estimate_gpu_memory_mb(service_name: str, gpu_layers: int) -> float:
    """Rough VRAM needed before starting a GPU-backed service."""
    if gpu_layers <= 0:
        return 0.0
    if service_name in ("main_llm", "soul"):
        return 8500.0
    return 1500.0


def get_profile_summary() -> Dict[str, Any]:
    profile = load_hardware_profile()
    if not profile:
        return {"loaded": False}
    return {
        "loaded": True,
        "machine_id": profile.get("machine_id"),
        "gpu_strategy": profile.get("gpu_strategy"),
        "deployment_mode": profile.get("deployment_mode"),
        "vram_total_mb": profile.get("vram_total_mb"),
        "vram_reserve_percent": profile.get("vram_reserve_percent"),
        "vram_budget_mb": profile.get("vram_budget_mb", vram_budget_mb(profile)),
        "ram_total_mb": profile.get("ram_total_mb"),
        "services": {
            name: {
                "port": cfg.get("port"),
                "gpu_layers": cfg.get("gpu_layers"),
                "n_threads": cfg.get("n_threads"),
                "conditional": cfg.get("conditional", False),
                "compute_mode": (
                    "gpu" if int(cfg.get("gpu_layers", 0) or 0) > 0 else "cpu"
                ),
            }
            for name, cfg in profile.get("services", {}).items()
        },
    }


def get_llm_compute_health() -> Dict[str, Any]:
    """VRAM budget + per-service CPU/GPU mode for /health."""
    profile = load_hardware_profile()
    summary = get_profile_summary()
    reserve_mb = vram_reserve_mb(profile)
    total_mb = int((profile or {}).get("vram_total_mb", 16384))
    budget_mb = int((profile or {}).get("vram_budget_mb", vram_budget_mb(profile)))

    services: Dict[str, Any] = {}
    for name, cfg in (summary.get("services") or {}).items():
        gpu_layers = int(cfg.get("gpu_layers", 0) or 0)
        services[name] = {
            "port": cfg.get("port"),
            "gpu_layers": gpu_layers,
            "n_threads": cfg.get("n_threads"),
            "compute_mode": cfg.get("compute_mode", "cpu" if gpu_layers <= 0 else "gpu"),
            "conditional_startup": bool(cfg.get("conditional", False)),
        }

    return {
        "loaded": summary.get("loaded", False),
        "gpu_strategy": summary.get("gpu_strategy"),
        "deployment_mode": summary.get("deployment_mode"),
        "vram_total_mb": total_mb,
        "vram_reserve_mb": reserve_mb,
        "vram_reserve_percent": int((profile or {}).get("vram_reserve_percent", 20)),
        "vram_budget_mb": budget_mb,
        "ram_total_mb": summary.get("ram_total_mb"),
        "services": services,
    }


def validate_services_alignment(
    services: List[Dict[str, Any]],
    *,
    source_label: str = "config",
) -> List[str]:
    """Compare service compute fields against hardware_profile.json."""
    profile = load_hardware_profile()
    if not profile:
        return []

    overrides = profile.get("services", {})
    errors: List[str] = []

    for entry in services:
        name = entry.get("name", "")
        ovr = overrides.get(name)
        if not ovr:
            continue
        for key in ("gpu_layers", "n_threads", "n_ctx"):
            if key not in ovr:
                continue
            expected = ovr[key]
            actual = entry.get(key)
            if actual is not None and actual != expected:
                errors.append(
                    f"{name}: {key} mismatch ({source_label}={actual}, "
                    f"hardware_profile={expected})"
                )
    return errors


def validate_registry_alignment(
    registry_items: List[Tuple[str, int, int, int]],
) -> List[str]:
    """
    registry_items: list of (service_id, gpu_layers, n_threads, n_ctx)
    """
    profile = load_hardware_profile()
    if not profile:
        return []

    overrides = profile.get("services", {})
    errors: List[str] = []

    for service_id, gpu_layers, n_threads, n_ctx in registry_items:
        ovr = overrides.get(service_id)
        if not ovr:
            continue
        checks = (
            ("gpu_layers", gpu_layers, ovr.get("gpu_layers")),
            ("n_threads", n_threads, ovr.get("n_threads")),
            ("n_ctx", n_ctx, ovr.get("n_ctx")),
        )
        for key, actual, expected in checks:
            if expected is not None and actual != expected:
                errors.append(
                    f"{service_id}: {key} mismatch "
                    f"(registry={actual}, hardware_profile={expected})"
                )
    return errors
