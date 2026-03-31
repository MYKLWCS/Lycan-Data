"""
github_profile.py — GitHub user profile search crawler.

Searches GitHub user API for a person's name or username.
Registered as "github_profile".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_GITHUB_URL = "https://api.github.com/search/users?q={query}&per_page=5"


@register("github_profile")
class GitHubProfileCrawler(HttpxCrawler):
    """
    Searches GitHub user API for a person's name.
    identifier: full name or GitHub username
    """

    platform = "github_profile"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    SOURCE_RELIABILITY = 0.70
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        url = _GITHUB_URL.format(query=quote_plus(query))
        resp = await self.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("GitHub JSON parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        items = payload.get("items") or []
        if not items:
            return self._result(identifier, found=False)

        profiles = [
            {
                "login": u.get("login"),
                "name": u.get("name"),
                "public_repos": u.get("public_repos"),
                "followers": u.get("followers"),
                "url": u.get("html_url"),
                "avatar_url": u.get("avatar_url"),
                "profile_photo_url": u.get("avatar_url"),
            }
            for u in items[:5]
        ]
        # Top result photo for easy access
        top_photo = profiles[0].get("profile_photo_url") if profiles else None
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={
                "profiles": profiles,
                "total_count": payload.get("total_count", len(profiles)),
                "profile_photo_url": top_photo,
            },
            source_reliability=self.SOURCE_RELIABILITY,
        )
