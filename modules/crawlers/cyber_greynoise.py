"""
cyber_greynoise.py — GreyNoise IP noise and classification crawler.

Uses the full context API (v2) when settings.greynoise_api_key is present,
otherwise falls back to the unauthenticated community endpoint (v3).

Registered as "cyber_greynoise".
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_COMMUNITY_URL = "https://api.greynoise.io/v3/community/{ip}"
_FULL_URL = "https://api.greynoise.io/v2/noise/context/{ip}"


def _parse_community(data: dict) -> dict[str, Any]:
    """Extract fields from the community (free) endpoint response."""
    return {
        "ip": data.get("ip", ""),
        "noise": data.get("noise", False),
        "riot": data.get("riot", False),
        "classification": data.get("classification", ""),
        "name": data.get("name", ""),
        "link": data.get("link", ""),
        "last_seen": data.get("last_seen", ""),
        "message": data.get("message", ""),
    }


def _parse_full(data: dict) -> dict[str, Any]:
    """Extract fields from the full context (authenticated) endpoint response."""
    return {
        "ip": data.get("ip", ""),
        "noise": data.get("noise", False),
        "riot": data.get("riot", False),
        "classification": data.get("classification", ""),
        "name": data.get("name", ""),
        "link": data.get("link", ""),
        "last_seen": data.get("last_seen", ""),
        "message": data.get("message", ""),
    }


@register("cyber_greynoise")
class GreyNoiseCrawler(CurlCrawler):
    """
    Queries GreyNoise for IP noise classification and threat context.

    identifier: IPv4 address

    Data keys returned:
        ip, noise, riot, classification, name, link, last_seen, message
    """

    platform = "cyber_greynoise"
    category = CrawlerCategory.CYBER
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        ip = identifier.strip()
        api_key: str = getattr(settings, "greynoise_api_key", "")

        if api_key:
            return await self._scrape_full(identifier, ip, api_key)
        return await self._scrape_community(identifier, ip)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_full(self, identifier: str, ip: str, api_key: str) -> CrawlerResult:
        url = _FULL_URL.format(ip=ip)
        headers = {
            "key": api_key,
            "Accept": "application/json",
        }
        resp = await self.get(url, headers=headers)

        if resp is None:
            # Fall through to community endpoint on failure
            logger.warning("GreyNoise full API failed for %s, trying community", ip)
            return await self._scrape_community(identifier, ip)

        if resp.status_code == 401:
            logger.warning("GreyNoise full API key invalid, trying community")
            return await self._scrape_community(identifier, ip)

        if resp.status_code == 404:
            return self._result(identifier, found=False, error="not_found", ip=ip)

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited", ip=ip)

        if resp.status_code != 200:
            return self._result(identifier, found=False, error=f"http_{resp.status_code}", ip=ip)

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("GreyNoise full JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error", ip=ip)

        parsed = _parse_full(data)
        found = parsed.get("noise", False) or parsed.get("riot", False)
        return self._result(identifier, found=found, api="full", **parsed)

    async def _scrape_community(self, identifier: str, ip: str) -> CrawlerResult:
        url = _COMMUNITY_URL.format(ip=ip)
        resp = await self.get(url)

        if resp is None:
            return self._result(identifier, found=False, error="http_error", ip=ip)

        if resp.status_code == 404:
            return self._result(identifier, found=False, error="not_found", ip=ip)

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited", ip=ip)

        if resp.status_code != 200:
            return self._result(identifier, found=False, error=f"http_{resp.status_code}", ip=ip)

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("GreyNoise community JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error", ip=ip)

        parsed = _parse_community(data)
        found = parsed.get("noise", False) or parsed.get("riot", False)
        return self._result(identifier, found=found, api="community", **parsed)
