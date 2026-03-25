"""
gdelt_mentions.py — GDELT Project API news mentions crawler.

Queries the GDELT Document API v2 for news articles mentioning a person.
Registered as "gdelt_mentions".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=artlist&format=json"


@register("gdelt_mentions")
class GdeltMentionsCrawler(HttpxCrawler):
    """
    Queries the GDELT Document API for news articles mentioning a person.
    identifier: full name (e.g. "John Doe")
    """

    platform = "gdelt_mentions"
    SOURCE_RELIABILITY = 0.55
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = f'"{identifier.strip()}"'
        url = _GDELT_URL.format(query=quote_plus(query))
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("GDELT JSON parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        raw_articles = payload.get("articles") or []
        if not raw_articles:
            return self._result(identifier, found=False)

        articles = [
            {
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "domain": a.get("domain", ""),
                "published": a.get("seendate", ""),
                "language": a.get("language", ""),
            }
            for a in raw_articles[:20]
        ]
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"articles": articles, "count": len(articles)},
            source_reliability=self.SOURCE_RELIABILITY,
        )
