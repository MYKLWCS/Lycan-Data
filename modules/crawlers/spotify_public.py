"""
spotify_public.py — Spotify public user search crawler.

Searches Spotify public user search endpoint (no OAuth for basic name lookup).
Registered as "spotify_public".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.spotify.com/v1/search?q={query}&type=user&limit=5"


@register("spotify_public")
class SpotifyPublicCrawler(HttpxCrawler):
    """
    Searches Spotify public user search endpoint (unauthenticated).
    identifier: person display name or username
    Note: Spotify's public search for users requires no OAuth for basic name lookup.
    """

    platform = "spotify_public"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    SOURCE_RELIABILITY = 0.40
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        url = _SEARCH_URL.format(query=quote_plus(query))
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("Spotify JSON parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        items = (payload.get("users") or {}).get("items") or []
        if not items:
            return self._result(identifier, found=False)

        users = [
            {
                "display_name": u.get("display_name"),
                "id": u.get("id"),
                "uri": u.get("uri"),
            }
            for u in items
        ]
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"users": users, "count": len(users)},
            source_reliability=self.SOURCE_RELIABILITY,
        )
