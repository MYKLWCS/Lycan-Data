"""
stackoverflow_profile.py — Stack Exchange API user profile search crawler.

Searches Stack Overflow users by display name via the Stack Exchange API.
Registered as "stackoverflow_profile".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_SO_URL = (
    "https://api.stackexchange.com/2.3/users"
    "?inname={query}&site=stackoverflow&order=desc&sort=reputation&pagesize=5"
)


@register("stackoverflow_profile")
class StackOverflowProfileCrawler(HttpxCrawler):
    """
    Searches Stack Overflow user API by name.
    identifier: full name or display name
    """

    platform = "stackoverflow_profile"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    SOURCE_RELIABILITY = 0.65
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        url = _SO_URL.format(query=quote_plus(query))
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("StackOverflow JSON parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        items = payload.get("items") or []
        if not items:
            return self._result(identifier, found=False)

        profiles = [
            {
                "user_id": u.get("user_id"),
                "display_name": u.get("display_name"),
                "reputation": u.get("reputation"),
                "badge_counts": u.get("badge_counts", {}),
                "url": u.get("link"),
                "location": u.get("location"),
                "website_url": u.get("website_url"),
            }
            for u in items[:5]
        ]
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"profiles": profiles, "count": len(profiles)},
            source_reliability=self.SOURCE_RELIABILITY,
        )
