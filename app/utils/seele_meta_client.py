"""Client for Seele Meta Controller — on-demand 8082/8083 lifecycle (Phase 6)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_ON_DEMAND_SERVICES = frozenset({"revise_llm", "logic_llm"})


def _base_url() -> str:
    from app.config import config

    return (config.SEELE_META_CONTROLLER_URL or "").rstrip("/")


def _enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "SEELE_META_CONTROLLER_ENABLED", False))


def _post_json(path: str, timeout: float) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    import httpx

    url = f"{_base_url()}{path}"
    try:
        response = httpx.post(url, timeout=timeout)
        if response.status_code >= 400:
            return False, f"http_{response.status_code}", None
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:200]}
        ok = bool(payload.get("success", response.status_code < 400))
        detail = str(payload.get("detail") or payload.get("error") or "ok")
        return ok, detail, payload
    except httpx.ConnectError:
        return False, "meta_controller_unreachable", None
    except httpx.TimeoutException:
        return False, "meta_controller_timeout", None
    except Exception as exc:
        return False, f"meta_controller_error:{type(exc).__name__}", None


def _get_json(path: str, timeout: float) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    import httpx

    url = f"{_base_url()}{path}"
    try:
        response = httpx.get(url, timeout=timeout)
        if response.status_code >= 400:
            return False, f"http_{response.status_code}", None
        return True, "ok", response.json()
    except httpx.ConnectError:
        return False, "meta_controller_unreachable", None
    except httpx.TimeoutException:
        return False, "meta_controller_timeout", None
    except Exception as exc:
        return False, f"meta_controller_error:{type(exc).__name__}", None


async def meta_controller_reachable(timeout: float = 2.0) -> Tuple[bool, str]:
    if not _enabled():
        return False, "meta_controller_disabled"
    loop = asyncio.get_running_loop()
    ok, detail, _ = await loop.run_in_executor(
        None,
        lambda: _get_json("/meta/health", timeout),
    )
    return ok, detail


async def list_meta_services(timeout: float = 3.0) -> Tuple[bool, Dict[str, Any]]:
    if not _enabled():
        return False, {"enabled": False}
    loop = asyncio.get_running_loop()
    ok, detail, payload = await loop.run_in_executor(
        None,
        lambda: _get_json("/meta/services", timeout),
    )
    if not ok or not payload:
        return False, {"enabled": True, "detail": detail}
    return True, payload


async def ensure_on_demand_service(
    service_name: str,
    *,
    timeout: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Ask Seele to start an on-demand LLM (revise_llm / logic_llm).
    No-op when meta controller disabled or service is already reachable.
    """
    if service_name not in _ON_DEMAND_SERVICES:
        return False, "not_on_demand_service"

    if not _enabled():
        return True, "meta_controller_disabled"

    from app.config import config

    start_timeout = float(timeout or config.SEELE_ON_DEMAND_START_TIMEOUT)
    loop = asyncio.get_running_loop()
    ok, detail, payload = await loop.run_in_executor(
        None,
        lambda: _post_json(f"/meta/ensure/{service_name}", start_timeout + 5.0),
    )
    if ok:
        return True, detail
    if payload and payload.get("already_running"):
        return True, "already_running"
    logger.warning(
        "[META] ensure_on_demand failed service=%s detail=%s",
        service_name,
        detail,
    )
    return False, detail


async def touch_on_demand_service(service_name: str, timeout: float = 2.0) -> None:
    """Refresh idle timer for a running on-demand service."""
    if not _enabled() or service_name not in _ON_DEMAND_SERVICES:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _post_json(f"/meta/touch/{service_name}", timeout),
    )


async def release_on_demand_service(service_name: str, timeout: float = 5.0) -> Tuple[bool, str]:
    if not _enabled() or service_name not in _ON_DEMAND_SERVICES:
        return True, "meta_controller_disabled"
    loop = asyncio.get_running_loop()
    ok, detail, _ = await loop.run_in_executor(
        None,
        lambda: _post_json(f"/meta/release/{service_name}", timeout),
    )
    return ok, detail


async def ensure_and_probe_llm(
    service_name: str,
    url: str,
    *,
    probe_timeout: float = 3.0,
) -> Tuple[bool, str]:
    """
    Ensure on-demand service via Meta Controller, invalidate probe cache, re-probe.
    """
    from app.utils.llm_availability import (
        invalidate_llm_availability_cache,
        is_service_reachable,
    )

    ensured, ensure_detail = await ensure_on_demand_service(service_name)
    if not ensured:
        return False, ensure_detail

    invalidate_llm_availability_cache()
    ok, probe_detail = await is_service_reachable(
        service_name,
        url,
        timeout=probe_timeout,
        use_cache=False,
    )
    if ok:
        await touch_on_demand_service(service_name)
    return ok, probe_detail if ok else f"ensure_ok_probe_failed:{probe_detail}"
