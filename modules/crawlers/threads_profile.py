"""
threads_profile.py — Threads.net profile crawler.

Fetches a Threads profile via the internal Graph API endpoint (?__a=1&__d=dis).
Registered as "threads_profile".
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("threads_profile")
class ThreadsProfileCrawler(HttpxCrawler):
    """
    Fetches a Threads profile via the internal Graph API.
    identifier: Threads handle (without @)
    """

    platform = "threads_profile"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    SOURCE_RELIABILITY = 0.50
    source_reliability = SOURCE_RELIABILITY
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@")
        url = f"https://www.threads.net/@{handle}?__a=1&__d=dis"
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            return self._result(handle, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("Threads JSON parse error for %s: %s", handle, exc)
            return self._result(handle, found=False, error="parse_error")

        user = (payload.get("data") or {}).get("user") or {}
        if not user:
            return self._result(handle, found=False)

        data = {
            "username": user.get("username", handle),
            "bio": user.get("biography", ""),
            "follower_count": (user.get("edge_followed_by") or {}).get("count"),
        }
        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=True,
            data=data,
            profile_url=f"https://www.threads.net/@{handle}",
            source_reliability=self.SOURCE_RELIABILITY,
        )
