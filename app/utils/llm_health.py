# app/utils/llm_health.py
"""LLM service reachability probes for health checks."""

from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def probe_llm_service(
    url: str,
    timeout: float = 3.0,
    api_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Probe an LLM HTTP service.

    Returns (is_available, detail_message).
    HTTP 401/403 on /v1/models counts as reachable (auth required but server up).
    """
    if not url:
        return False, "empty_url"

    base = url.rstrip('/')

    try:
        import httpx

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for path in ("/health", "/v1/models"):
            try:
                response = httpx.get(
                    f"{base}{path}",
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True,
                )
                if response.status_code < 500:
                    if path == "/v1/models" and response.status_code in (401, 403):
                        return True, f"reachable_auth_required_http_{response.status_code}"
                    if response.status_code < 400:
                        return True, f"reachable_http_{response.status_code}"
            except httpx.TimeoutException:
                return False, f"timeout_{path}"
            except httpx.ConnectError:
                return False, f"connection_refused_{path}"
            except Exception as exc:
                logger.debug("LLM probe error for %s%s: %s", base, path, exc)

        return False, "all_probe_paths_failed"

    except ImportError:
        return False, "httpx_not_installed"
