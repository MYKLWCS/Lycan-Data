"""
FlareSolverrCrawler — extends CurlCrawler with Cloudflare JS-challenge bypass.

Uses Byparr (FlareSolverr-compatible API) as a Docker sidecar (localhost:8191)
running Camoufox (stealth Firefox) to solve Cloudflare challenges and return
the rendered HTML + cookies.

Health cache is CLASS-LEVEL so all instances share the same probe result:
- _fs_healthy = True → positive result cached indefinitely
- _fs_healthy = False → negative result cached for _FS_NEGATIVE_TTL seconds (60s)
  to avoid hammering a down sidecar on every request

Fallback chain: Byparr → CurlCrawler (chrome latest) → httpx
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from modules.crawlers.curl_base import CurlCrawler
from shared.config import settings

logger = logging.getLogger(__name__)

_FS_URL = settings.flaresolverr_url
_FS_TIMEOUT = 60
_FS_NEGATIVE_TTL = 60  # seconds before re-probing a down sidecar


class FlareSolverrCrawler(CurlCrawler):
    """CurlCrawler variant that routes Cloudflare-protected URLs through FlareSolverr."""

    # Class-level health cache — shared across all instances
    _fs_healthy: bool | None = None
    _fs_checked_at: float = 0.0

    @classmethod
    async def _probe_flaresolverr(cls) -> bool:
        """Check if the FlareSolverr sidecar is reachable. Caches result."""
        now = time.monotonic()
        if cls._fs_healthy is True:
            return True  # positive: indefinite cache
        if cls._fs_healthy is False and (now - cls._fs_checked_at) < _FS_NEGATIVE_TTL:
            return False  # negative: within TTL
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                _health_url = settings.flaresolverr_url.rsplit("/v1", 1)[0] + "/health"
                resp = await client.get(_health_url)
                cls._fs_healthy = resp.status_code == 200
        except Exception:
            cls._fs_healthy = False
        cls._fs_checked_at = time.monotonic()
        return cls._fs_healthy

    async def fs_get(self, url: str, **kwargs) -> Any:
        """
        GET via FlareSolverr. Falls back to CurlCrawler.get() if sidecar unavailable.
        Returns a response-like object with .text and .status_code attributes.
        """
        if not await self._probe_flaresolverr():
            logger.debug("FlareSolverr unavailable, falling back to CurlCrawler for %s", url)
            return await self.get(url, **kwargs)

        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": _FS_TIMEOUT * 1000,
        }
        try:
            async with httpx.AsyncClient(timeout=_FS_TIMEOUT + 10) as client:
                resp = await client.post(_FS_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "ok":
                    raise RuntimeError(f"FlareSolverr error: {data.get('message')}")

                solution = data["solution"]

                class _FsResponse:
                    text = solution.get("response", "")
                    status_code = solution.get("status", 200)
                    cookies = {c["name"]: c["value"] for c in solution.get("cookies", [])}

                return _FsResponse()
        except Exception as exc:
            logger.warning("FlareSolverr request failed (%s), falling back to CurlCrawler", exc)
            FlareSolverrCrawler._fs_healthy = False
            FlareSolverrCrawler._fs_checked_at = time.monotonic()
            return await self.get(url, **kwargs)
