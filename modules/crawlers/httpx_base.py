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

    async def get(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """GET with Tor proxy and timeout. Returns None on error."""
        proxy = self.get_proxy()
        proxies = {"all://": proxy} if proxy else None
        try:
            async with httpx.AsyncClient(
                proxies=proxies,
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LycanBot/1.0)"},
            ) as client:
                response = await client.get(url, **kwargs)
                return response
        except Exception as exc:
            logger.warning("httpx GET failed for %s: %s", url, exc)
            return None

    async def post(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """POST with Tor proxy."""
        proxy = self.get_proxy()
        proxies = {"all://": proxy} if proxy else None
        try:
            async with httpx.AsyncClient(
                proxies=proxies,
                timeout=20.0,
                follow_redirects=True,
            ) as client:
                response = await client.post(url, **kwargs)
                return response
        except Exception as exc:
            logger.warning("httpx POST failed for %s: %s", url, exc)
            return None
