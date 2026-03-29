from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("tiktok")
class TikTokCrawler(CurlCrawler):
    """Scrapes public TikTok profiles via web (no auth required for public data)."""

    platform = "tiktok"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = SOURCE_RELIABILITY.get("tiktok", 0.50)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@").lower()
        url = f"https://www.tiktok.com/@{handle}"

        response = await self.get(url, headers={"Accept-Language": "en-US,en;q=0.9"})
        if response is None or response.status_code != 200:
            return self._result(handle, found=False, error="http_error")

        if (
            "Couldn't find this account" in response.text
            or "not available" in response.text.lower()
        ):
            return self._result(handle, found=False, handle=handle)

        data = self._parse(response.text, handle)
        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=bool(data.get("display_name") or data.get("follower_count")),
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    def _parse(self, html: str, handle: str) -> dict:
        data: dict = {"handle": handle}
        soup = BeautifulSoup(html, "html.parser")

        # TikTok embeds JSON in <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        script = soup.find("script", {"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"})
        if script and script.string:
            import json

            try:
                jdata = json.loads(script.string)
                user = (
                    jdata.get("__DEFAULT_SCOPE__", {})
                    .get("webapp.user-detail", {})
                    .get("userInfo", {})
                )
                user_info = user.get("user", {})
                stats = user.get("stats", {})
                if user_info:
                    data["display_name"] = user_info.get("nickname")
                    data["bio"] = user_info.get("signature", "")[:500]
                    data["is_verified"] = user_info.get("verified", False)
                    data["platform_user_id"] = user_info.get("id")
                if stats:
                    data["follower_count"] = stats.get("followerCount")
                    data["following_count"] = stats.get("followingCount")
                    data["post_count"] = stats.get("videoCount")
                    data["likes_count"] = stats.get("heartCount")
                return data
            except (json.JSONDecodeError, AttributeError):
                pass

        # Fallback: meta tags
        title = soup.find("title")
        if title:
            data["display_name"] = title.get_text(strip=True).split("|")[0].strip()
        desc = soup.find("meta", {"name": "description"})
        if desc:
            data["bio"] = desc.get("content", "")[:300]

        return data
