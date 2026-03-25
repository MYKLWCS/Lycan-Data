"""
faa_aircraft_registry.py — FAA aircraft registry crawler.

Searches the FAA aircraft registry for aircraft registered to a person or entity.
"""

from __future__ import annotations

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult


class FaaAircraftRegistryCrawler(BaseCrawler):
    platform = "faa_aircraft_registry"
    source_reliability = 0.95
    requires_tor = False
    proxy_tier = "direct"

    async def scrape(self, identifier: str) -> CrawlerResult:
        return CrawlerResult(found=False, data={}, platform=self.platform, identifier=identifier)
