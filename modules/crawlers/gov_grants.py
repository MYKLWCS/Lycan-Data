"""
gov_grants.py — Grants.gov federal grant opportunity search.

Searches the Grants.gov v1 API for federal funding opportunities by keyword
or organization name, returning opportunity details including award ceiling,
agency, and open/close dates.

Registered as "gov_grants".
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_GRANTS_URL = "https://api.grants.gov/v1/api/search2"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _parse_opportunities(data: dict) -> list[dict[str, Any]]:
    """Extract opportunity fields from Grants.gov search response."""
    opportunities: list[dict[str, Any]] = []
    # Response structure varies; common keys are oppHits or hits
    hits = data.get("oppHits") or data.get("hits", {}).get("hits", []) or data.get("hits", []) or []
    for item in hits[:20]:
        if not isinstance(item, dict):
            continue
        # Some responses nest fields under _source
        source = item.get("_source", item)
        opportunities.append(
            {
                "opportunityTitle": source.get("opportunityTitle"),
                "opportunityNumber": source.get("opportunityNumber"),
                "agencyName": source.get("agencyName"),
                "openDate": source.get("openDate"),
                "closeDate": source.get("closeDate"),
                "awardCeiling": source.get("awardCeiling"),
                "awardFloor": source.get("awardFloor"),
                "cfdaNumber": source.get("cfdaNumber"),
                "opportunityCategory": source.get("opportunityCategory"),
                "fundingActivityCategory": source.get("fundingActivityCategory"),
            }
        )
    return opportunities


@register("gov_grants")
class GrantsCrawler(HttpxCrawler):
    """
    Searches Grants.gov for federal funding opportunities.

    identifier: organization name or funding keyword

    Data keys returned:
        opportunities   — list of grant opportunity records (up to 20)
        total           — total matching records reported by the API
    """

    platform = "gov_grants"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        payload = {
            "rows": 20,
            "keyword": query,
            "sortBy": "openDate|desc",
        }

        resp = await self.post(_GRANTS_URL, json=payload, headers=_HEADERS)

        if resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
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
            data = resp.json()
            opportunities = _parse_opportunities(data)
            total: int = (
                data.get("totalRecords")
                or data.get("hits", {}).get("total", {}).get("value", 0)
                or len(opportunities)
            )
        except Exception as exc:
            logger.warning("Grants.gov JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(opportunities) > 0,
            opportunities=opportunities,
            total=total,
        )
