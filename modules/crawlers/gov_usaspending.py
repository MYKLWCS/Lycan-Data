"""
gov_usaspending.py — USASpending.gov federal contract and award search.

Searches the USASpending API for federal contract awards by recipient name,
returning award IDs, amounts, and awarding agencies.

Registered as "gov_usaspending".
"""
from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


def _parse_awards(data: dict) -> tuple[list[dict[str, Any]], int]:
    """Return (awards, total_count) from USASpending search response."""
    results: list[dict[str, Any]] = data.get("results", [])
    page_meta = data.get("page_metadata", {})
    total: int = page_meta.get("total", len(results))
    return results, total


@register("gov_usaspending")
class UsaSpendingCrawler(HttpxCrawler):
    """
    Searches USASpending.gov for federal contract and grant awards.

    identifier: company or person name (e.g. "Lockheed Martin")

    Data keys returned:
        awards  — list of award records (up to 20)
        count   — total matching awards reported by the API
    """

    platform = "gov_usaspending"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        body: dict[str, Any] = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],
                "recipient_search_text": [query],
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency"],
            "page": 1,
            "limit": 20,
            "sort": "Award Amount",
            "order": "desc",
        }

        resp = await self.post(_URL, json=body)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                awards=[],
                count=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                awards=[],
                count=0,
            )

        try:
            payload = resp.json()
            awards, total_count = _parse_awards(payload)
        except Exception as exc:
            logger.warning("USASpending JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                awards=[],
                count=0,
            )

        return self._result(
            identifier,
            found=len(awards) > 0,
            awards=awards[:20],
            count=total_count,
        )
