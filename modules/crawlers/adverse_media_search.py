"""
adverse_media_search.py — Stub crawler for adverse/negative media search.

Searches news sources and media databases for negative coverage of a person.
"""

from __future__ import annotations

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult


class AdverseMediaSearchCrawler(BaseCrawler):
    platform = "adverse_media_search"
    source_reliability = 0.7
    requires_tor = False
    proxy_tier = "direct"

    async def scrape(self, identifier: str) -> CrawlerResult:
        return CrawlerResult(found=False, data={}, platform=self.platform, identifier=identifier)
