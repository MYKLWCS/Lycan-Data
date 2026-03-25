"""
financial_finra.py — FINRA BrokerCheck individual search.

Searches the FINRA BrokerCheck public API for registered brokers and
investment advisors by name, returning registration scope, disclosure
flags, and hit counts.

Registered as "financial_finra".
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
    "https://api.brokercheck.finra.org/search/individual"
    "?query={query}&hl=true&includePrevious=true"
    "&nRows=10&start=0&wantCounts=false"
)

_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://brokercheck.finra.org/",
    "X-Requested-With": "XMLHttpRequest",
}


def _parse_brokers(payload: dict) -> tuple[list[dict[str, Any]], int]:
    """Return (brokers, total_count) from BrokerCheck API response."""
    hits_block = payload.get("hits", {})
    total = 0
    total_meta = hits_block.get("total", {})
    if isinstance(total_meta, dict):
        total = total_meta.get("value", 0)
    elif isinstance(total_meta, int):  # pragma: no branch
        total = total_meta

    brokers: list[dict[str, Any]] = []
    for hit in hits_block.get("hits", []):
        source = hit.get("_source", {})
        brokers.append(
            {
                "ind_source_id": source.get("ind_source_id", ""),
                "bc_firstname": source.get("ind_firstname", ""),
                "bc_lastname": source.get("ind_lastname", ""),
                "ind_bc_scope": source.get("ind_bc_scope", ""),
                "ind_bc_disc_fl": source.get("ind_bc_disc_fl", "N") == "Y",
            }
        )
    return brokers, total


@register("financial_finra")
class FinancialFinraCrawler(HttpxCrawler):
    """
    Searches FINRA BrokerCheck for registered broker/advisor records.

    identifier: broker or advisor full name (e.g. "John Smith")

    Data keys returned:
        brokers     — list of matching records
        total       — total hit count reported by the API
    """

    platform = "financial_finra"
    category = CrawlerCategory.FINANCIAL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)
        url = _SEARCH_URL.format(query=encoded)

        resp = await self.get(url, headers=_HEADERS)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                brokers=[],
                total=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                brokers=[],
                total=0,
            )

        try:
            payload = resp.json()
            brokers, total = _parse_brokers(payload)
        except Exception as exc:
            logger.warning("FINRA BrokerCheck parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                brokers=[],
                total=0,
            )

        return self._result(
            identifier,
            found=len(brokers) > 0,
            brokers=brokers,
            total=total,
        )
