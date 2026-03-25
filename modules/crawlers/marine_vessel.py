"""
marine_vessel.py — Marine vessel registry crawler.

Searches vessel registries (USCG, IMO) for vessels registered to a person or entity.
"""

from __future__ import annotations

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit


class MarineVesselCrawler(BaseCrawler):
    platform = "marine_vessel"
    category = CrawlerCategory.VEHICLE
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.9
    requires_tor = False
    proxy_tier = "direct"

    async def scrape(self, identifier: str) -> CrawlerResult:
        return CrawlerResult(found=False, data={}, platform=self.platform, identifier=identifier)
