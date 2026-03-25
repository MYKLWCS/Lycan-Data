"""
marine_vessel.py — Marine vessel registry crawler.

Searches vessel registries (USCG, IMO) for vessels registered to a person or entity.
"""

from __future__ import annotations

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult


class MarineVesselCrawler(BaseCrawler):
    platform = "marine_vessel"
    source_reliability = 0.9
    requires_tor = False
    proxy_tier = "direct"

    async def scrape(self, identifier: str) -> CrawlerResult:
        return CrawlerResult(found=False, data={}, platform=self.platform, identifier=identifier)
