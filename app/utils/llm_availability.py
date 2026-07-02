"""Cached LLM reachability probes for fast degraded routing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.utils.llm_health import probe_llm_service

_CACHE: Dict[str, Tuple[float, bool, str]] = {}
_DEFAULT_TTL_SEC = 5.0


def _cache_get(key: str, ttl: float) -> Optional[Tuple[bool, str]]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, ok, detail = entry
    if time.monotonic() - ts > ttl:
        return None
    return ok, detail


def _cache_set(key: str, ok: bool, detail: str) -> None:
    _CACHE[key] = (time.monotonic(), ok, detail)


def invalidate_llm_availability_cache() -> None:
    _CACHE.clear()


async def probe_llm_async(url: str, timeout: float = 2.0) -> Tuple[bool, str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: probe_llm_service(url, timeout=timeout),
    )


async def is_service_reachable(
    cache_key: str,
    url: str,
    *,
    timeout: float = 2.0,
    use_cache: bool = True,
    cache_ttl: float = _DEFAULT_TTL_SEC,
) -> Tuple[bool, str]:
    if use_cache:
        cached = _cache_get(cache_key, cache_ttl)
        if cached is not None:
            return cached

    ok, detail = await probe_llm_async(url, timeout=timeout)
    if use_cache:
        _cache_set(cache_key, ok, detail)
    return ok, detail


@dataclass
class LLMAvailabilitySnapshot:
    main_llm: bool = False
    revise_llm: bool = False
    logic_llm: bool = False
    memory_llm: bool = False
    emobloom_llm: bool = False
    details: Dict[str, str] = None

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = {}

    @property
    def star_soul_available(self) -> bool:
        return self.main_llm

    @property
    def star_execution_available(self) -> bool:
        return self.logic_llm or self.revise_llm

    @property
    def any_generative_llm(self) -> bool:
        return self.main_llm or self.logic_llm or self.revise_llm


async def snapshot_llm_availability(
    *,
    timeout: float = 2.0,
    use_cache: bool = True,
) -> LLMAvailabilitySnapshot:
    from app.config import config

    probes = (
        ("main_llm", config.MAIN_LLM_URL),
        ("revise_llm", config.REVISE_LLM_URL),
        ("logic_llm", config.LOGIC_LLM_URL),
        ("memory_llm", config.MEMORY_LLM_URL),
        ("emobloom_llm", config.EMOBLOOM_LLM_URL),
    )

    results = await asyncio.gather(
        *[
            is_service_reachable(
                key,
                url,
                timeout=timeout,
                use_cache=use_cache,
            )
            for key, url in probes
        ],
        return_exceptions=True,
    )

    snap = LLMAvailabilitySnapshot()
    for (key, _url), result in zip(probes, results):
        if isinstance(result, Exception):
            snap.details[key] = f"probe_error:{type(result).__name__}"
            continue
        ok, detail = result
        setattr(snap, key, ok)
        snap.details[key] = detail

    return snap


async def is_main_llm_reachable(
    timeout: float = 2.0,
    use_cache: bool = True,
) -> Tuple[bool, str]:
    from app.config import config

    return await is_service_reachable(
        "main_llm",
        config.MAIN_LLM_URL,
        timeout=timeout,
        use_cache=use_cache,
    )
