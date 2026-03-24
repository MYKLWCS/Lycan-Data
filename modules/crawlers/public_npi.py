"""
public_npi.py — NPI (National Provider Identifier) registry scraper.

Uses the free, public CMS NPI Registry API to look up healthcare providers
by name or organization.

API docs: https://npiregistry.cms.hhs.gov/api-page

Registered as "public_npi".

identifier format: "First Last" (individual) or "org:Organization Name"
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://npiregistry.cms.hhs.gov/api/"
_INDIVIDUAL_URL = _BASE_URL + "?version=2.1&first_name={first}&last_name={last}&limit=10"
_ORG_URL = _BASE_URL + "?version=2.1&organization_name={org}&limit=10"

_MAX_RESULTS = 10


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_name(identifier: str) -> tuple[str, str]:
    """
    Split "First Last" into (first, last).
    For single-word identifiers returns (identifier, "").
    """
    parts = identifier.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return identifier.strip(), ""


def _parse_providers(data: dict) -> list[dict[str, Any]]:
    """
    Normalise NPI API response into a list of provider records.

    Each result has:
      number, basic: {first_name, last_name, credential, gender,
                      enumeration_date, status},
      addresses: [{address_1, city, state, postal_code}],
      taxonomies: [{desc, primary}]
    """
    providers: list[dict[str, Any]] = []
    for item in data.get("results", [])[:_MAX_RESULTS]:
        basic = item.get("basic", {})
        addrs = item.get("addresses", [])
        taxs = item.get("taxonomies", [])

        # Build display name
        if basic.get("authorized_official_first_name"):
            # org record
            name = (
                basic.get("authorized_official_first_name", "")
                + " "
                + basic.get("authorized_official_last_name", "")
            ).strip()
            org_name = basic.get("organization_name", "")
        else:
            name = (basic.get("first_name", "") + " " + basic.get("last_name", "")).strip()
            org_name = basic.get("organization_name", "")

        # Primary address
        primary_addr = next(
            (a for a in addrs if a.get("address_purpose") == "LOCATION"),
            addrs[0] if addrs else {},
        )

        # Primary specialty
        primary_tax = next(
            (t for t in taxs if t.get("primary")),
            taxs[0] if taxs else {},
        )

        providers.append(
            {
                "npi": item.get("number", ""),
                "name": name or org_name,
                "org_name": org_name,
                "credential": basic.get("credential", ""),
                "status": basic.get("status", ""),
                "gender": basic.get("gender", ""),
                "enumeration_date": basic.get("enumeration_date", ""),
                "specialty": primary_tax.get("desc", ""),
                "address": primary_addr.get("address_1", ""),
                "city": primary_addr.get("city", ""),
                "state": primary_addr.get("state", ""),
                "zip": primary_addr.get("postal_code", ""),
            }
        )
    return providers


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("public_npi")
class PublicNPICrawler(HttpxCrawler):
    """
    Queries the CMS NPI Registry public API for healthcare providers.

    identifier:
        "John Smith"           → individual search
        "org:Mayo Clinic"      → organization search

    Data keys returned:
        providers    — list of {npi, name, credential, specialty, address, state}
        result_count — integer
        query        — original identifier
    """

    platform = "public_npi"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        is_org = query.lower().startswith("org:")

        if is_org:
            org_name = query[4:].strip()
            url = _ORG_URL.format(org=quote_plus(org_name))
        else:
            first, last = _split_name(query)
            url = _INDIVIDUAL_URL.format(
                first=quote_plus(first),
                last=quote_plus(last),
            )

        response = await self.get(url)

        if response is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                providers=[],
                result_count=0,
                query=query,
            )

        if response.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{response.status_code}",
                providers=[],
                result_count=0,
                query=query,
            )

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("NPI: JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="json_parse_error",
                providers=[],
                result_count=0,
                query=query,
            )

        providers = _parse_providers(data)
        result_count = data.get("result_count", len(providers))

        return self._result(
            identifier,
            found=len(providers) > 0,
            providers=providers,
            result_count=result_count,
            query=query,
        )
