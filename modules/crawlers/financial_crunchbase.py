"""
financial_crunchbase.py — Crunchbase organization intelligence crawler.

Primary: Crunchbase v4 search API (requires settings.crunchbase_api_key).
Fallback: Scrapes the public Crunchbase search page when no key is configured.

Registered as "financial_crunchbase".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_API_URL = "https://api.crunchbase.com/api/v4/searches/organizations"
_PUBLIC_URL = "https://www.crunchbase.com/textsearch?q={query}"

_FIELD_IDS = [
    "short_description",
    "founded_on",
    "funding_total",
    "num_funding_rounds",
    "num_employees_enum",
]

_SCRAPE_ORG_RE = re.compile(r'"identifier"\s*:\s*\{[^}]*"value"\s*:\s*"([^"]+)"', re.DOTALL)


def _build_api_payload(identifier: str) -> dict[str, Any]:
    return {
        "field_ids": _FIELD_IDS,
        "predicate": {
            "field_id": "facet_ids",
            "operator_id": "includes",
            "values": ["company"],
        },
        "query": [
            {
                "type": "predicate",
                "field_id": "name",
                "operator_id": "contains",
                "values": [identifier],
            }
        ],
        "limit": 5,
    }


def _parse_api_response(data: dict) -> list[dict[str, Any]]:
    organizations: list[dict[str, Any]] = []
    for entity in data.get("entities", []):
        props = entity.get("properties", {})

        # funding_total may be a nested dict with value_usd
        funding_total = props.get("funding_total")
        if isinstance(funding_total, dict):
            funding_total = funding_total.get("value_usd", funding_total)

        # founded_on may be a nested dict with value
        founded_on = props.get("founded_on")
        if isinstance(founded_on, dict):
            founded_on = founded_on.get("value", founded_on)

        organizations.append(
            {
                "name": entity.get("identifier", {}).get("value", ""),
                "short_description": props.get("short_description", ""),
                "founded_on": founded_on,
                "funding_total": funding_total,
                "num_funding_rounds": props.get("num_funding_rounds"),
                "num_employees_enum": props.get("num_employees_enum", ""),
            }
        )
    return organizations


def _scrape_public_names(html: str) -> list[dict[str, Any]]:
    """
    Minimal extraction of organization names from the public Crunchbase
    search page HTML. Returns name-only records as a degraded fallback.
    """
    names = list(dict.fromkeys(_SCRAPE_ORG_RE.findall(html)))[:5]
    return [{"name": n, "short_description": "", "source": "public_scrape"} for n in names]


@register("financial_crunchbase")
class CrunchbaseCrawler(CurlCrawler):
    """
    Searches Crunchbase for company/organization intelligence.

    Primary mode (API key present): Crunchbase v4 searches/organizations endpoint.
    Fallback mode (no key): Public Crunchbase search page HTML scrape.

    identifier: company name (e.g. "OpenAI", "Tesla")

    Data keys returned:
        organizations — list of {name, short_description, founded_on,
                                  funding_total, num_funding_rounds}
        source        — "api" or "public_scrape"
    """

    platform = "financial_crunchbase"
    category = CrawlerCategory.FINANCIAL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.75
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key: str = getattr(settings, "crunchbase_api_key", "")

        if api_key:
            return await self._scrape_api(identifier, api_key)
        return await self._scrape_public(identifier)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_api(self, identifier: str, api_key: str) -> CrawlerResult:
        payload = _build_api_payload(identifier.strip())
        params = {"user_key": api_key}
        resp = await self.post(_API_URL, json=payload, params=params)

        if resp is None:
            return self._result(identifier, found=False, error="http_error", organizations=[])

        if resp.status_code == 401:
            return self._result(identifier, found=False, error="invalid_api_key", organizations=[])

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited", organizations=[])

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                organizations=[],
            )

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Crunchbase API JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error", organizations=[])

        organizations = _parse_api_response(data)
        return self._result(
            identifier,
            found=len(organizations) > 0,
            source="api",
            organizations=organizations,
        )

    async def _scrape_public(self, identifier: str) -> CrawlerResult:
        encoded = quote_plus(identifier.strip())
        url = _PUBLIC_URL.format(query=encoded)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = await self.get(url, headers=headers)

        if resp is None:
            return self._result(identifier, found=False, error="http_error", organizations=[])

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited", organizations=[])

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                organizations=[],
            )

        organizations = _scrape_public_names(resp.text)
        return self._result(
            identifier,
            found=len(organizations) > 0,
            source="public_scrape",
            organizations=organizations,
        )
