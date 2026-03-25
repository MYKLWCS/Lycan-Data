"""
sec_insider.py — SEC EDGAR Form 4 insider trading filings crawler.

Searches SEC EDGAR full-text search for Form 4 insider trading filings.
Registered as "sec_insider".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SEC_EFTS_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q={query}&forms=4&dateRange=custom&startdt=2020-01-01"
)


@register("sec_insider")
class SecInsiderCrawler(HttpxCrawler):
    """
    Searches SEC EDGAR full-text search for Form 4 insider trading filings.
    identifier: person full name (e.g. "John Doe")
    """

    platform = "sec_insider"
    SOURCE_RELIABILITY = 0.90
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = f'"{identifier.strip()}"'
        url = _SEC_EFTS_URL.format(query=quote_plus(query))
        resp = await self.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "LycanBot research@lycan.ai",
            },
        )
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("SEC EFTS JSON parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        hits = (payload.get("hits") or {}).get("hits") or []
        if not hits:
            return self._result(identifier, found=False)

        filings = []
        for h in hits[:20]:
            src = h.get("_source") or {}
            filings.append({
                "entity_name": src.get("entity_name", ""),
                "form_type": src.get("form_type", "4"),
                "file_date": src.get("file_date", ""),
                "period_of_report": src.get("period_of_report", ""),
                "file_num": src.get("file_num", ""),
            })

        total = ((payload.get("hits") or {}).get("total") or {}).get("value", len(filings))
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"filings": filings, "total": total},
            source_reliability=self.SOURCE_RELIABILITY,
        )
