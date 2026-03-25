"""
sanctions_opensanctions.py — OpenSanctions unified sanctions/PEP/watchlist API.

Searches the OpenSanctions API for a given name across 40+ global lists
including OFAC, EU, UN, Interpol Red Notices, PEPs, and crime lists.

Registered as "sanctions_opensanctions".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_API_BASE = "https://api.opensanctions.org"
_SEARCH_URL = _API_BASE + "/search/default?q={query}&limit=10&fuzzy=false"
_HEADERS = {"Accept": "application/json"}


def _parse_entity(entity: dict) -> dict:
    """Extract relevant fields from an OpenSanctions entity record."""
    props = entity.get("properties", {})
    return {
        "id": entity.get("id"),
        "caption": entity.get("caption", ""),
        "schema": entity.get("schema", ""),
        "datasets": entity.get("datasets", []),
        "referents": entity.get("referents", []),
        "names": props.get("name", []),
        "aliases": props.get("alias", []),
        "birth_date": props.get("birthDate", []),
        "nationality": props.get("nationality", []),
        "topics": entity.get("properties", {}).get("topics", []),
        "country": props.get("country", []),
    }


@register("sanctions_opensanctions")
class OpenSanctionsCrawler(HttpxCrawler):
    """
    Queries the OpenSanctions /search endpoint for a name.

    OpenSanctions aggregates 40+ global sanctions, PEP, and watchlists including
    OFAC SDN, EU Financial Sanctions, UN Consolidated List, Interpol Red Notices,
    FBI Most Wanted, UK HMT OFSI, and many others.

    identifier: person or entity name (e.g. "Vladimir Putin")

    Data keys returned:
        results     — list of matching entity records (up to 10)
        total       — total match count reported by API
        datasets    — union of all dataset sources across matches
    """

    platform = "sanctions_opensanctions"
    category = CrawlerCategory.SANCTIONS_AML
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        if not query:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                results=[],
                total=0,
                datasets=[],
            )

        url = _SEARCH_URL.format(query=quote_plus(query))
        resp = await self.get(url, headers=_HEADERS)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                results=[],
                total=0,
                datasets=[],
            )

        if resp.status_code == 429:
            return self._result(
                identifier,
                found=False,
                error="rate_limited",
                results=[],
                total=0,
                datasets=[],
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                results=[],
                total=0,
                datasets=[],
            )

        try:
            payload = resp.json()
        except Exception as exc:
            logger.warning("OpenSanctions JSON parse error for %r: %s", identifier, exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                results=[],
                total=0,
                datasets=[],
            )

        raw_results = payload.get("results", [])
        total = payload.get("total", {})
        if isinstance(total, dict):
            total_count: int = total.get("value", len(raw_results))
        else:
            total_count = int(total) if total else len(raw_results)

        entities = [_parse_entity(e) for e in raw_results[:10]]

        # Collect all unique dataset names across matches
        all_datasets: set[str] = set()
        for e in entities:
            all_datasets.update(e.get("datasets", []))

        return self._result(
            identifier,
            found=len(entities) > 0,
            results=entities,
            total=total_count,
            datasets=sorted(all_datasets),
        )
