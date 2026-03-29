"""
news_wikipedia.py — Wikipedia search and Wikidata entity lookup crawler.

Searches Wikipedia for up to 5 articles matching the identifier, fetches
the summary of the top result, and queries Wikidata for up to 3 entity matches.

Registered as "news_wikipedia".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, quote_plus

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_WP_SEARCH_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&list=search&srsearch={query}&format=json&srlimit=5"
)
_WP_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_WD_SEARCH_URL = (
    "https://www.wikidata.org/w/api.php"
    "?action=wbsearchentities&search={query}&language=en&format=json&limit=3"
)

_WP_HEADERS = {"Accept": "application/json"}


def _parse_wp_search(data: dict) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in data.get("query", {}).get("search", []):
        results.append(
            {
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "pageid": item.get("pageid"),
                "wordcount": item.get("wordcount"),
                "timestamp": item.get("timestamp", ""),
            }
        )
    return results


def _parse_wikidata(data: dict) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for item in data.get("search", []):
        entities.append(
            {
                "id": item.get("id", ""),
                "label": item.get("label", ""),
                "description": item.get("description", ""),
                "aliases": [a.get("value", "") for a in item.get("aliases", [])],
                "url": item.get("url", ""),
            }
        )
    return entities


def _parse_summary(data: dict) -> dict[str, Any]:
    return {
        "title": data.get("title", ""),
        "extract": data.get("extract", ""),
        "description": data.get("description", ""),
        "thumbnail": data.get("thumbnail", {}).get("source", ""),
        "content_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
    }


@register("news_wikipedia")
class WikipediaCrawler(CurlCrawler):
    """
    Searches Wikipedia and Wikidata for a person or entity name.

    identifier: person or entity name (e.g. "Elon Musk", "Tesla Inc")

    Data keys returned:
        wikipedia_results  — list of {title, snippet, pageid, wordcount, timestamp}
        wikidata_entities  — list of {id, label, description, aliases, url}
        top_summary        — {title, extract, description, thumbnail, content_url}
    """

    platform = "news_wikipedia"
    category = CrawlerCategory.NEWS_MEDIA
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        # Run Wikipedia search
        wp_results = await self._wp_search(encoded)

        # Fetch summary for first result
        top_summary: dict[str, Any] = {}
        if wp_results:
            top_title = wp_results[0].get("title", "")
            if top_title:
                top_summary = await self._wp_summary(top_title)

        # Run Wikidata entity search
        wd_entities = await self._wikidata_search(encoded)

        found = bool(wp_results or wd_entities)

        return self._result(
            identifier,
            found=found,
            wikipedia_results=wp_results,
            wikidata_entities=wd_entities,
            top_summary=top_summary,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _wp_search(self, encoded_query: str) -> list[dict[str, Any]]:
        url = _WP_SEARCH_URL.format(query=encoded_query)
        resp = await self.get(url, headers=_WP_HEADERS)

        if resp is None or resp.status_code != 200:
            logger.debug(
                "Wikipedia search failed (status=%s)",
                resp.status_code if resp else "None",
            )
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Wikipedia search JSON parse error: %s", exc)
            return []

        return _parse_wp_search(data)

    async def _wp_summary(self, title: str) -> dict[str, Any]:
        encoded_title = quote(title, safe="")
        url = _WP_SUMMARY_URL.format(title=encoded_title)
        resp = await self.get(url, headers=_WP_HEADERS)

        if resp is None or resp.status_code != 200:
            return {}

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Wikipedia summary JSON parse error: %s", exc)
            return {}

        return _parse_summary(data)

    async def _wikidata_search(self, encoded_query: str) -> list[dict[str, Any]]:
        url = _WD_SEARCH_URL.format(query=encoded_query)
        resp = await self.get(url, headers=_WP_HEADERS)

        if resp is None or resp.status_code != 200:
            logger.debug(
                "Wikidata search failed (status=%s)",
                resp.status_code if resp else "None",
            )
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Wikidata JSON parse error: %s", exc)
            return []

        return _parse_wikidata(data)
