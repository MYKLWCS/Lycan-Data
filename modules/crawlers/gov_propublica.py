"""
gov_propublica.py — ProPublica Nonprofit Explorer API search.

Searches the ProPublica Nonprofit Explorer for IRS Form 990 data
by organization name, returning EIN, NTEE code, income, and filing dates.

Registered as "gov_propublica".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_URL = "https://projects.propublica.org/nonprofits/api/v2/search.json?q={query}"


def _parse_organizations(data: dict) -> tuple[list[dict[str, Any]], int]:
    """Return (organizations, total_results) from ProPublica Nonprofit Explorer response."""
    orgs_raw: list[dict] = data.get("organizations", [])
    organizations: list[dict[str, Any]] = []
    for org in orgs_raw:
        organizations.append(
            {
                "name": org.get("name", ""),
                "city": org.get("city", ""),
                "state": org.get("state", ""),
                "ein": org.get("ein", ""),
                "ntee_code": org.get("ntee_code", ""),
                "income_amount": org.get("income_amount"),
                "filing_date": org.get("filing_date", ""),
            }
        )
    total_results: int = data.get("total_results", len(organizations))
    return organizations, total_results


@register("gov_propublica")
class ProPublicaCrawler(HttpxCrawler):
    """
    Searches ProPublica Nonprofit Explorer for IRS 990 nonprofit records.

    identifier: nonprofit organization name (e.g. "American Red Cross")

    Data keys returned:
        organizations  — list of nonprofit records (up to 20)
        total_results  — total matching organizations reported by the API
    """

    platform = "gov_propublica"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.95
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
                organizations=[],
                total_results=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                organizations=[],
                total_results=0,
            )

        try:
            payload = resp.json()
            organizations, total_results = _parse_organizations(payload)
        except Exception as exc:
            logger.warning("ProPublica Nonprofit JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                organizations=[],
                total_results=0,
            )

        return self._result(
            identifier,
            found=len(organizations) > 0,
            organizations=organizations[:20],
            total_results=total_results,
        )
