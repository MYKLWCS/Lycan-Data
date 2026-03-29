from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com/users/{username}"
GITHUB_FIELDS = (
    "name",
    "bio",
    "public_repos",
    "followers",
    "following",
    "company",
    "location",
    "blog",
    "avatar_url",
    "created_at",
)


@register("github")
class GitHubCrawler(HttpxCrawler):
    """Scrapes public GitHub profiles via the unauthenticated API."""

    platform = "github"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.65
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.lstrip("@")
        url = API_URL.format(username=username)

        response = await self.get(url, headers={"Accept": "application/vnd.github+json"})
        if response is None:
            return self._result(username, found=False, error="http_error")

        if response.status_code == 404:
            return self._result(username, found=False)

        if response.status_code != 200:
            return self._result(
                username,
                found=False,
                error=f"unexpected_status_{response.status_code}",
            )

        try:
            payload = response.json()
        except Exception as exc:
            logger.debug("GitHub JSON parse error: %s", exc)
            return self._result(username, found=False, error="json_parse_error")

        data: dict = {"handle": username}
        for field in GITHUB_FIELDS:
            if field in payload:
                data[field] = payload[field]

        profile_url = f"https://github.com/{username}"
        return CrawlerResult(
            platform=self.platform,
            identifier=username,
            found=True,
            data=data,
            profile_url=profile_url,
            source_reliability=self.source_reliability,
        )
