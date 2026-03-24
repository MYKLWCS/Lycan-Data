"""
gov_nmls.py — NMLS Consumer Access mortgage licensee search.

Queries the NMLS Consumer Access API for licensed mortgage brokers and lenders
by name, returning entity names, primary state, license status, and license list.

Registered as "gov_nmls".
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_NMLS_URL = "https://www.nmlsconsumeraccess.org/api/Search/GetIndividualSearchResult"
_NMLS_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.nmlsconsumeraccess.org",
    "Referer": "https://www.nmlsconsumeraccess.org/",
}


def _parse_licensees(data: Any) -> list[dict[str, Any]]:
    """Extract licensee fields from NMLS API response."""
    licensees: list[dict[str, Any]] = []

    # Response may be a list directly or wrapped in a dict
    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("IndividualList", "Results", "data", "items"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        licensees.append(
            {
                "EntityName": item.get("EntityName") or item.get("FullName"),
                "NmlsId": item.get("NmlsId"),
                "PrimaryState": item.get("PrimaryState"),
                "LicenseStatus": item.get("LicenseStatus"),
                "licenseList": item.get("licenseList", []),
                "EntityType": item.get("EntityType"),
                "OtherTradeName": item.get("OtherTradeName"),
            }
        )
    return licensees


@register("gov_nmls")
class NmlsCrawler(HttpxCrawler):
    """
    Searches NMLS Consumer Access for licensed mortgage brokers and lenders.

    identifier: mortgage broker or lender name

    Data keys returned:
        licensees   — list of licensee records (up to 20)
    """

    platform = "gov_nmls"
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        payload = {
            "Name": query,
            "State": "",
            "ZipCode": "",
            "LicenseNumber": "",
        }

        resp = await self.post(_NMLS_URL, json=payload, headers=_NMLS_HEADERS)

        if resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if resp.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
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
            licensees = _parse_licensees(data)
        except Exception as exc:
            logger.warning("NMLS JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(licensees) > 0,
            licensees=licensees,
        )
