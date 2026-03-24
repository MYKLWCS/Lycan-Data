"""
cyber_urlscan.py — URLScan.io domain/URL intelligence crawler.

Queries the URLScan.io search API for scan results associated with a domain or URL.
Registered as "cyber_urlscan".
Optional API key (settings.urlscan_api_key) — works without one at reduced rate limits.
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings

logger = logging.getLogger(__name__)

_URLSCAN_URL = "https://urlscan.io/api/v1/search/"


def _parse_results(raw_results: list[dict]) -> list[dict]:
    """Extract task, stats, and verdicts from each scan result."""
    out = []
    for entry in raw_results:
        task = entry.get("task", {})
        stats = entry.get("stats", {})
        verdicts = entry.get("verdicts", {})
        overall = verdicts.get("overall", {})
        out.append(
            {
                "url": task.get("url"),
                "time": task.get("time"),
                "malicious_requests": stats.get("malicious"),
                "verdict_malicious": overall.get("malicious"),
                "verdict_score": overall.get("score"),
            }
        )
    return out


@register("cyber_urlscan")
class CyberURLScanCrawler(HttpxCrawler):
    """
    Searches URLScan.io for historical scan data on a domain or URL.

    API key is optional — unauthenticated requests are rate-limited.
    source_reliability is 0.85.
    Does not require Tor.
    """

    platform = "cyber_urlscan"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        target = identifier.strip()

        headers: dict[str, str] = {"User-Agent": "Lycan-OSINT/1.0"}
        api_key = getattr(settings, "urlscan_api_key", "")
        if api_key:
            headers["API-Key"] = api_key

        params = {
            "q": f"domain:{target}",
            "size": 10,
        }

        response = await self.get(_URLSCAN_URL, headers=headers, params=params)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            raw = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        raw_results = raw.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []

        results = _parse_results(raw_results)

        return self._result(
            identifier,
            found=bool(results),
            results=results[:10],
            total=raw.get("total", 0),
        )
