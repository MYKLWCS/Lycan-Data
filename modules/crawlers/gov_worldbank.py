"""
gov_worldbank.py — World Bank country GDP and metadata lookup.

Resolves a country name or ISO-2 code against the World Bank API, returning
basic country metadata and the last 5 years of GDP (current USD) data.

Registered as "gov_worldbank".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_COUNTRY_SEARCH_URL = (
    "https://api.worldbank.org/v2/country"
    "?name={name}&format=json&per_page=5"
)
_GDP_URL = (
    "https://api.worldbank.org/v2/country/{code}"
    "/indicator/NY.GDP.MKTP.CD?format=json&mrv=5"
)

# Common ISO-2 codes for fast path when identifier is already a code
_ISO2_LEN = 2


def _looks_like_iso2(value: str) -> bool:
    return len(value) == _ISO2_LEN and value.isalpha()


def _parse_country(data: list) -> dict[str, Any] | None:
    """Extract country metadata from World Bank country search response."""
    if not data or len(data) < 2:
        return None
    items = data[1]
    if not items:
        return None
    item = items[0]
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "iso2Code": item.get("iso2Code"),
        "region": item.get("region", {}).get("value"),
        "incomeLevel": item.get("incomeLevel", {}).get("value"),
        "lendingType": item.get("lendingType", {}).get("value"),
        "capitalCity": item.get("capitalCity"),
        "longitude": item.get("longitude"),
        "latitude": item.get("latitude"),
    }


def _parse_gdp(data: list) -> list[dict[str, Any]]:
    """Extract GDP observations from World Bank indicator response."""
    if not data or len(data) < 2:
        return []
    observations: list[dict[str, Any]] = []
    for obs in (data[1] or [])[:5]:
        if not isinstance(obs, dict):
            continue
        observations.append(
            {
                "year": obs.get("date"),
                "value_usd": obs.get("value"),
                "indicator": obs.get("indicator", {}).get("value"),
            }
        )
    return observations


@register("gov_worldbank")
class WorldBankCrawler(HttpxCrawler):
    """
    Looks up country metadata and GDP data from the World Bank API.

    identifier: country name (e.g. "South Africa") or ISO-2 code (e.g. "ZA")

    Data keys returned:
        country     — basic country metadata dict
        gdp_data    — list of up to 5 annual GDP observations (current USD)
    """

    platform = "gov_worldbank"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        # Resolve country code
        country_code: str | None = None
        country_info: dict[str, Any] | None = None

        if _looks_like_iso2(query):
            country_code = query.upper()
        else:
            encoded = quote_plus(query)
            search_url = _COUNTRY_SEARCH_URL.format(name=encoded)
            search_resp = await self.get(search_url)

            if search_resp is None:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="http_error",
                    source_reliability=self.source_reliability,
                )

            if search_resp.status_code != 200:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error=f"http_{search_resp.status_code}",
                    source_reliability=self.source_reliability,
                )

            try:
                search_data = search_resp.json()
                country_info = _parse_country(search_data)
                if country_info:
                    country_code = country_info.get("iso2Code")
            except Exception as exc:
                logger.warning("WorldBank country search parse error: %s", exc)
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="parse_error",
                    source_reliability=self.source_reliability,
                )

        if not country_code:
            return self._result(
                identifier,
                found=False,
                country=None,
                gdp_data=[],
            )

        # Fetch GDP data
        gdp_url = _GDP_URL.format(code=country_code)
        gdp_resp = await self.get(gdp_url)

        gdp_data: list[dict[str, Any]] = []
        if gdp_resp is not None and gdp_resp.status_code == 200:
            try:
                gdp_data = _parse_gdp(gdp_resp.json())
            except Exception as exc:
                logger.warning("WorldBank GDP parse error: %s", exc)

        # If we skipped the country search (ISO-2 shortcut), build minimal info
        if country_info is None:
            country_info = {"iso2Code": country_code}

        found = country_info is not None and bool(country_code)

        return self._result(
            identifier,
            found=found,
            country=country_info,
            gdp_data=gdp_data,
        )
