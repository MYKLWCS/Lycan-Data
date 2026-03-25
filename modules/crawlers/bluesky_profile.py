"""
bluesky_profile.py — Bluesky AT Protocol profile crawler.

Fetches a Bluesky profile via the public AT Protocol API (public.api.bsky.app).
Registered as "bluesky_profile".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"


@register("bluesky_profile")
class BlueskyProfileCrawler(HttpxCrawler):
    """
    Fetches a Bluesky profile via the public AT Protocol API.
    identifier: Bluesky handle (e.g. user.bsky.social)
    """

    platform = "bluesky_profile"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    SOURCE_RELIABILITY = 0.55
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@")
        url = f"{_BASE}?actor={quote_plus(handle)}"
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            return self._result(handle, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("Bluesky JSON parse error for %s: %s", handle, exc)
            return self._result(handle, found=False, error="parse_error")

        display_name = payload.get("displayName")
        if not display_name and not payload.get("handle"):
            return self._result(handle, found=False)

        data = {
            "display_name": display_name or "",
            "bio": payload.get("description", ""),
            "follower_count": payload.get("followersCount"),
            "following_count": payload.get("followsCount"),
            "post_count": payload.get("postsCount"),
            "handle": payload.get("handle", handle),
        }
        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=True,
            data=data,
            profile_url=f"https://bsky.app/profile/{handle}",
            source_reliability=self.SOURCE_RELIABILITY,
        )
