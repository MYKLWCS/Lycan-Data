"""
gov_gleif.py — GLEIF (Global LEI Foundation) legal entity identifier search.

Queries the GLEIF open API for Legal Entity Identifiers (LEIs) by fuzzy
company name or LEI code. Returns completions and full-text search results.

Registered as "gov_gleif".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_FUZZY_URL = "https://api.gleif.org/api/v1/fuzzycompletions?field=entity.legalName&q={query}"
_FULLTEXT_URL = "https://api.gleif.org/api/v1/lei-records?filter[fulltext]={query}&page[size]=10"


def _parse_fuzzy(data: list) -> list[dict[str, Any]]:
    """Extract lei+name pairs from a GLEIF fuzzycompletions response."""
    completions: list[dict[str, Any]] = []
    for item in data:
        completions.append(
            {
                "lei": item.get("lei", ""),
                "name": item.get("value", item.get("name", "")),
            }
        )
    return completions


@register("gov_gleif")
class GleifCrawler(HttpxCrawler):
    """
    Searches GLEIF for Legal Entity Identifiers (LEIs).

    identifier: company name or existing LEI code (e.g. "Goldman Sachs")

    Data keys returned:
        completions  — list of {lei, name} pairs from fuzzy completion (up to 10)
        query        — the original search term
    """

    platform = "gov_gleif"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        fuzzy_url = _FUZZY_URL.format(query=encoded)
        resp = await self.get(fuzzy_url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                completions=[],
                query=query,
            )

        if resp.status_code != 200:
            # Fall back to full-text search on non-200
            logger.warning(
                "GLEIF fuzzy returned HTTP %s — attempting full-text fallback",
                resp.status_code,
            )
            completions = await self._fulltext_fallback(encoded)
            return self._result(
                identifier,
                found=len(completions) > 0,
                completions=completions[:10],
                query=query,
            )

        try:
            payload = resp.json()
            # GLEIF fuzzycompletions returns a plain JSON array
            raw_list: list = payload if isinstance(payload, list) else payload.get("data", [])
            completions = _parse_fuzzy(raw_list)
        except Exception as exc:
            logger.warning("GLEIF fuzzy JSON parse error: %s", exc)
            completions = await self._fulltext_fallback(encoded)

        return self._result(
            identifier,
            found=len(completions) > 0,
            completions=completions[:10],
            query=query,
        )

    async def _fulltext_fallback(self, encoded: str) -> list[dict[str, Any]]:
        """Attempt a full-text LEI record search as a fallback."""
        url = _FULLTEXT_URL.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code != 200:
            return []
        try:
            payload = resp.json()
            records = payload.get("data", [])
            completions: list[dict[str, Any]] = []
            for record in records:
                attrs = record.get("attributes", {})
                entity = attrs.get("entity", {})
                legal_name = entity.get("legalName", {})
                completions.append(
                    {
                        "lei": record.get("id", attrs.get("lei", "")),
                        "name": legal_name.get("name", "")
                        if isinstance(legal_name, dict)
                        else str(legal_name),
                    }
                )
            return completions
        except Exception as exc:
            logger.warning("GLEIF full-text fallback parse error: %s", exc)
            return []
