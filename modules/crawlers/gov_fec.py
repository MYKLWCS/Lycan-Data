"""
gov_fec.py — FEC Campaign Finance candidate search.

Searches the Federal Election Commission open API for candidate records
by name, returning party, state, office, total receipts, and election years.

Registered as "gov_fec".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from shared.config import settings
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE = "https://api.open.fec.gov/v1"
_SEARCH = _BASE + "/candidates/search/?api_key={api_key}&q={query}&per_page=20"


def _parse_candidates(data: dict) -> tuple[list[dict[str, Any]], int]:
    """Return (candidates, total_count) from FEC API response."""
    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        results.append(
            {
                "name":            item.get("name", ""),
                "party":           item.get("party", ""),
                "state":           item.get("state", ""),
                "office":          item.get("office", ""),
                "total_receipts":  item.get("total_receipts"),
                "election_years":  item.get("election_years", []),
            }
        )
    pagination = data.get("pagination", {})
    total_count: int = pagination.get("count", len(results))
    return results, total_count


@register("gov_fec")
class FecCrawler(HttpxCrawler):
    """
    Searches the FEC open API for campaign finance candidate records.

    identifier: person name (e.g. "Joe Biden")

    Data keys returned:
        candidates  — list of candidate records (up to 20)
        count       — total matching candidates reported by the API
    """

    platform = "gov_fec"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)
        api_key: str = getattr(settings, "fec_api_key", "DEMO_KEY")

        url = _SEARCH.format(api_key=api_key, query=encoded)
        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                candidates=[],
                count=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                candidates=[],
                count=0,
            )

        try:
            payload = resp.json()
            candidates, total_count = _parse_candidates(payload)
        except Exception as exc:
            logger.warning("FEC JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                candidates=[],
                count=0,
            )

        return self._result(
            identifier,
            found=len(candidates) > 0,
            candidates=candidates[:20],
            count=total_count,
        )
