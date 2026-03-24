from __future__ import annotations
import logging
from typing import Any

import httpx

from modules.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


class HttpxCrawler(BaseCrawler):
    """
    Lightweight httpx-based scraper for APIs and simple pages.
    No browser — fast, low resource.
    """

    def _client(self, **kwargs: Any) -> httpx.AsyncClient:
        """Build AsyncClient with optional SOCKS5 proxy (httpx 0.28+ compatible)."""
        proxy = self.get_proxy()
        transport = None
        if proxy:
            try:
                transport = httpx.AsyncHTTPTransport(proxy=proxy)
            except Exception:
                pass  # proxy unavailable — run direct
        return httpx.AsyncClient(
            transport=transport,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LycanBot/1.0)"},
            **kwargs,
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """GET with Tor proxy and timeout. Returns None on error."""
        try:
            async with self._client() as client:
                return await client.get(url, **kwargs)
        except Exception as exc:
            logger.warning("httpx GET failed for %s: %s", url, exc)
            return None

    async def post(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """POST with Tor proxy."""
        try:
            async with self._client() as client:
                return await client.post(url, **kwargs)
        except Exception as exc:
            logger.warning("httpx POST failed for %s: %s", url, exc)
            return None
