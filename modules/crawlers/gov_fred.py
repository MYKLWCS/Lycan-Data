"""
gov_fred.py — St. Louis Fed FRED economic data series search.

Searches the Federal Reserve Bank of St. Louis FRED API for economic data
series by name or keyword. Uses DEMO_KEY when no API key is configured,
which is sufficient for low-volume OSINT queries.

Registered as "gov_fred".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_FRED_URL = (
    "https://api.stlouisfed.org/fred/series/search"
    "?search_text={query}&api_key={key}&file_type=json&limit=10"
)


def _parse_series(data: dict) -> list[dict[str, Any]]:
    """Extract series fields from FRED search response."""
    series_list: list[dict[str, Any]] = []
    for item in data.get("seriess", [])[:10]:
        if not isinstance(item, dict):
            continue
        series_list.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "frequency": item.get("frequency"),
                "units": item.get("units"),
                "last_updated": item.get("last_updated"),
                "popularity": item.get("popularity"),
                "observation_start": item.get("observation_start"),
                "observation_end": item.get("observation_end"),
                "seasonal_adjustment": item.get("seasonal_adjustment"),
                "notes": item.get("notes"),
            }
        )
    return series_list


@register("gov_fred")
class FredCrawler(HttpxCrawler):
    """
    Searches the FRED API for economic data series by keyword.

    Uses settings.fred_api_key when available; falls back to DEMO_KEY for
    unauthenticated access (rate limited to ~120 req/min per IP).

    identifier: economic indicator name (e.g. "unemployment rate", "GDP")

    Data keys returned:
        series      — list of matching FRED series (up to 10)
        count       — total matching series reported by the API
    """

    platform = "gov_fred"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key: str = getattr(settings, "fred_api_key", "") or "DEMO_KEY"

        query = identifier.strip()
        encoded = quote_plus(query)

        url = _FRED_URL.format(query=encoded, key=api_key)
        resp = await self.get(url)

        if resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if resp.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if resp.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{resp.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            payload = resp.json()
            series = _parse_series(payload)
            count: int = payload.get("count", len(series))
        except Exception as exc:
            logger.warning("FRED JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(series) > 0,
            series=series,
            count=count,
        )
