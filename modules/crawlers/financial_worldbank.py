"""
financial_worldbank.py — World Bank economic indicators lookup.

Resolves a country name or ISO-2 code to structured economic data:
GDP, CPI, and unemployment for the last 5 years.
No API key required. Registered as "financial_worldbank".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://api.worldbank.org/v2"
_COUNTRY_SEARCH_URL = _BASE + "/country?name={name}&format=json"
_INDICATOR_URL = _BASE + "/country/{country}/indicator/{indicator}?format=json&mrv=5"

# Indicators to fetch
_INDICATORS = {
    "gdp": "NY.GDP.MKTP.CD",
    "cpi": "FP.CPI.TOTL",
    "unemployment": "SL.UEM.TOTL.ZS",
}


def _parse_indicator_series(data: list) -> list[dict]:
    """
    World Bank returns a two-element list: [pagination, [records]].
    Extract year+value pairs from the records list.
    """
    if not isinstance(data, list) or len(data) < 2:
        return []
    records = data[1] or []
    out = []
    for rec in records:
        if rec is None:
            continue
        out.append(
            {
                "year": rec.get("date", ""),
                "value": rec.get("value"),
            }
        )
    return out


def _resolve_country_info(data: list) -> dict | None:
    """
    Parse country search response to extract iso2code and metadata.
    Returns None when no result found.
    """
    if not isinstance(data, list) or len(data) < 2:
        return None
    records = data[1]
    if not records:
        return None
    first = records[0]
    return {
        "iso2": first.get("iso2Code", ""),
        "name": first.get("name", ""),
        "capital": first.get("capitalCity", ""),
        "region": (first.get("region") or {}).get("value", ""),
        "income_level": (first.get("incomeLevel") or {}).get("value", ""),
    }


@register("financial_worldbank")
class FinancialWorldBankCrawler(HttpxCrawler):
    """
    Retrieves World Bank economic indicators for a given country.

    identifier: ISO-2 country code (e.g. "US") or country name (e.g. "Nigeria").

    Data keys returned:
        country_info    — name, capital, region, income_level
        gdp_data        — list of {year, value} for GDP (USD)
        cpi_data        — list of {year, value} for CPI
        unemployment_data — list of {year, value} for unemployment rate
    """

    platform = "financial_worldbank"
    category = CrawlerCategory.FINANCIAL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        # If the identifier looks like an ISO-2 code already, skip search
        if len(query) == 2 and query.isalpha():
            iso2 = query.upper()
            country_info = {
                "iso2": iso2,
                "name": iso2,
                "capital": "",
                "region": "",
                "income_level": "",
            }
            # Still attempt a lookup to fill in metadata
            search_url = _COUNTRY_SEARCH_URL.format(name=quote_plus(iso2))
            search_resp = await self.get(search_url)
            if search_resp is not None and search_resp.status_code == 200:
                try:
                    info = _resolve_country_info(search_resp.json())
                    if info:  # pragma: no branch
                        country_info = info
                except Exception as exc:
                    logger.warning("WorldBank country metadata parse error: %s", exc)
        else:
            # Resolve name to ISO-2 code
            search_url = _COUNTRY_SEARCH_URL.format(name=quote_plus(query))
            search_resp = await self.get(search_url)

            if search_resp is None:
                return self._result(
                    identifier,
                    found=False,
                    error="http_error",
                    country_info=None,
                    gdp_data=[],
                    cpi_data=[],
                    unemployment_data=[],
                )

            if search_resp.status_code != 200:
                return self._result(
                    identifier,
                    found=False,
                    error=f"http_{search_resp.status_code}",
                    country_info=None,
                    gdp_data=[],
                    cpi_data=[],
                    unemployment_data=[],
                )

            try:
                country_info = _resolve_country_info(search_resp.json())
            except Exception as exc:
                logger.warning("WorldBank country search parse error: %s", exc)
                country_info = None

            if not country_info:
                return self._result(
                    identifier,
                    found=False,
                    error="country_not_found",
                    country_info=None,
                    gdp_data=[],
                    cpi_data=[],
                    unemployment_data=[],
                )

            iso2 = country_info["iso2"]

        # Fetch each indicator
        indicator_results: dict[str, list[dict]] = {}
        for key, code in _INDICATORS.items():
            url = _INDICATOR_URL.format(country=iso2, indicator=code)
            resp = await self.get(url)
            if resp is not None and resp.status_code == 200:
                try:
                    indicator_results[key] = _parse_indicator_series(resp.json())
                except Exception as exc:
                    logger.warning("WorldBank indicator %s parse error: %s", code, exc)
                    indicator_results[key] = []
            else:
                indicator_results[key] = []

        return self._result(
            identifier,
            found=True,
            country_info=country_info,
            gdp_data=indicator_results.get("gdp", []),
            cpi_data=indicator_results.get("cpi", []),
            unemployment_data=indicator_results.get("unemployment", []),
        )
