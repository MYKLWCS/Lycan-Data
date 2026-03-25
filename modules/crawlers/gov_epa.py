"""
gov_epa.py — EPA ECHO facility compliance search.

Queries the EPA Enforcement and Compliance History Online (ECHO) REST API
for regulated facilities by name, returning facility details and compliance
status including quarters with non-compliance.

Registered as "gov_epa".
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

_ECHO_URL = (
    "https://echo.epa.gov/Rest/services/searchFacilities/search"
    "?output=JSON&p_nm={name}&p_per_page=20"
)


def _parse_facilities(data: dict) -> list[dict[str, Any]]:
    """Extract facility records from ECHO API response."""
    results: list[dict[str, Any]] = []
    # ECHO wraps results inside Results -> Results array
    outer = data.get("Results", data)
    items = outer.get("Results", []) if isinstance(outer, dict) else []
    if not items and isinstance(data, dict):
        # Some ECHO responses use a flat list
        for key in ("Facilities", "FRS_FACILITIES", "ECHO_EXPORTER"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "CWPName": item.get("CWPName"),
                "CWPCity": item.get("CWPCity"),
                "CWPState": item.get("CWPState"),
                "CWPSic": item.get("CWPSic"),
                "CWPStatus": item.get("CWPStatus"),
                "CWPQtrsWithNC": item.get("CWPQtrsWithNC"),
                "FacLat": item.get("FacLat"),
                "FacLong": item.get("FacLong"),
                "RegistryId": item.get("RegistryId"),
                "FacFIPSCode": item.get("FacFIPSCode"),
            }
        )
    return results


@register("gov_epa")
class EpaCrawler(HttpxCrawler):
    """
    Searches EPA ECHO for regulated facility compliance records.

    identifier: facility or company name

    Data keys returned:
        facilities  — list of facility records (up to 20) with compliance data
    """

    platform = "gov_epa"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        url = _ECHO_URL.format(name=encoded)
        resp = await self.get(url)

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
            payload = resp.json()
            facilities = _parse_facilities(payload)
        except Exception as exc:
            logger.warning("EPA ECHO JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(facilities) > 0,
            facilities=facilities,
        )
