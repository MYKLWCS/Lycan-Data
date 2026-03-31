"""
gov_fdic.py — FDIC BankFind Suite bank institution search.

Searches the FDIC public API for insured bank and thrift institutions
by name or city, returning asset size, location, and report dates.

Registered as "gov_fdic".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_URL = (
    "https://banks.data.fdic.gov/api/institutions"
    "?search={query}&fields=NAME,CITY,STNAME,ASSET,REPDTE"
    "&limit=20&sort_by=ASSET&sort_order=DESC"
)


def _parse_institutions(data: dict) -> tuple[list[dict[str, Any]], int]:
    """Return (institutions, total) from FDIC BankFind response."""
    raw: list[dict] = data.get("data", [])
    institutions: list[dict[str, Any]] = []
    for item in raw:
        record = item.get("data", item)
        institutions.append(
            {
                "name": record.get("NAME", ""),
                "city": record.get("CITY", ""),
                "state": record.get("STNAME", ""),
                "assets": record.get("ASSET"),
                "report_date": record.get("REPDTE", ""),
            }
        )
    meta = data.get("meta", {})
    total: int = meta.get("total", len(institutions))
    return institutions, total


@register("gov_fdic")
class FdicCrawler(HttpxCrawler):
    """
    Searches FDIC BankFind for insured depository institutions.

    identifier: bank name or city (e.g. "Wells Fargo" or "Dallas")

    Data keys returned:
        institutions  — list of institution records (up to 20)
        total         — total matching institutions reported by the API
    """

    platform = "gov_fdic"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        url = _URL.format(query=encoded)
        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                institutions=[],
                total=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                institutions=[],
                total=0,
            )

        try:
            payload = resp.json()
            institutions, total = _parse_institutions(payload)
        except Exception as exc:
            logger.warning("FDIC JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                institutions=[],
                total=0,
            )

        return self._result(
            identifier,
            found=len(institutions) > 0,
            institutions=institutions[:20],
            total=total,
        )
