"""
gov_uspto_trademarks.py — USPTO trademark search via USPTO IBD API.

Searches the USPTO Integrated Business Databases API for trademark records
by mark name or owner name. No authentication required.
Registered as "gov_uspto_trademarks".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://developer.uspto.gov/ibd-api/v1/application/status?searchText={query}&start=0&rows=10"
)


def _parse_trademarks(payload: dict) -> tuple[list[dict[str, Any]], int]:
    """
    Extract trademark records from USPTO IBD API response.
    Returns (trademarks, total_count).
    """
    body = payload.get("body", {})
    docs = body.get("docs", [])
    total = body.get("numFound", len(docs))

    trademarks: list[dict[str, Any]] = []
    for doc in docs:
        trademarks.append(
            {
                "serialNumber": doc.get("serialNumber", ""),
                "registrationNumber": doc.get("registrationNumber", ""),
                "wordMark": doc.get("wordMark", ""),
                "ownerName": doc.get("ownerName", ""),
                "status": doc.get("statusCode", ""),
                "filingDate": doc.get("filingDate", ""),
            }
        )
    return trademarks, total


@register("gov_uspto_trademarks")
class GovUsptoTrademarksCrawler(HttpxCrawler):
    """
    Searches the USPTO IBD API for trademark records by name or owner.

    identifier: brand/trademark name or owner/company name.

    Data keys returned:
        trademarks  — list of trademark records (up to 10)
        total       — total matching records
    """

    platform = "gov_uspto_trademarks"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)
        url = _SEARCH_URL.format(query=encoded)

        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                trademarks=[],
                total=0,
            )

        if resp.status_code == 404:
            return self._result(
                identifier,
                found=False,
                error="not_found",
                trademarks=[],
                total=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                trademarks=[],
                total=0,
            )

        try:
            payload = resp.json()
            trademarks, total = _parse_trademarks(payload)
        except Exception as exc:
            logger.warning("USPTO trademarks parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                trademarks=[],
                total=0,
            )

        return self._result(
            identifier,
            found=len(trademarks) > 0,
            trademarks=trademarks,
            total=total,
        )
