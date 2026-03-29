"""
people_intelx.py — Intelligence X (IntelX) API crawler.

Searches the IntelX data lake for an identifier across dark web,
data breaches, Telegram, and paste sites.
Registered as "people_intelx".
"""

from __future__ import annotations

import logging
import os

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://2.intelx.io/intelligent/search"
_RESULT_URL = "https://2.intelx.io/intelligent/search/result"


@register("people_intelx")
class IntelXCrawler(CurlCrawler):
    """
    Searches the Intelligence X platform for an identifier.

    IntelX indexes dark web, Telegram, breach databases, paste sites,
    and other OSINT sources. Requires INTELX_API_KEY env var.
    """

    platform = "people_intelx"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.70
    requires_tor = False

    def _api_key(self) -> str | None:
        return os.getenv("INTELX_API_KEY")

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key = self._api_key()
        if not api_key:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="INTELX_API_KEY not set",
                source_reliability=self.source_reliability,
            )

        headers = {
            "x-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "Lycan-OSINT/1.0",
        }

        # Step 1 — submit search
        try:
            search_resp = await self.post(
                _SEARCH_URL,
                json={"term": identifier.strip(), "maxresults": 100, "media": 0, "sort": 4},
                headers=headers,
            )
        except Exception as exc:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        if search_resp is None or search_resp.status_code not in (200, 201):
            status = search_resp.status_code if search_resp is not None else "none"
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"search_http_{status}",
                source_reliability=self.source_reliability,
            )

        try:
            search_data = search_resp.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_search_json",
                source_reliability=self.source_reliability,
            )

        search_id = search_data.get("id")
        if not search_id:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_search_id",
                source_reliability=self.source_reliability,
            )

        # Step 2 — fetch results
        try:
            results_resp = await self.get(
                f"{_RESULT_URL}?id={search_id}&limit=100&offset=0",
                headers=headers,
            )
        except Exception as exc:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        if results_resp is None or results_resp.status_code != 200:
            status = results_resp.status_code if results_resp is not None else "none"
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"results_http_{status}",
                source_reliability=self.source_reliability,
            )

        try:
            results_data = results_resp.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_results_json",
                source_reliability=self.source_reliability,
            )

        records = results_data.get("records", [])
        hits = []
        for rec in records:
            hits.append(
                {
                    "name": rec.get("name", ""),
                    "type": rec.get("type", ""),
                    "date": rec.get("date", ""),
                    "bucket": rec.get("bucket", ""),
                }
            )

        return self._result(
            identifier,
            found=bool(hits),
            query=identifier.strip(),
            hits=hits,
            total=results_data.get("total", len(hits)),
        )
