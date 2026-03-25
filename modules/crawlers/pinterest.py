from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

NOT_FOUND_SENTINEL = "This page doesn't exist"
FOLLOWER_RE = re.compile(r"(\d[\d,]*)\s+follower", re.IGNORECASE)


@register("pinterest")
class PinterestCrawler(CurlCrawler):
    """Scrapes public Pinterest profiles via OG meta tags."""

    platform = "pinterest"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.45
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.lstrip("@").lower()
        url = f"https://www.pinterest.com/{username}/"

        response = await self.get(url)
        if response is None:
            return self._result(username, found=False, error="http_error")

        if response.status_code == 404:
            return self._result(username, found=False)

        text = response.text
        if NOT_FOUND_SENTINEL in text:
            return self._result(username, found=False)

        soup = BeautifulSoup(text, "html.parser")
        data = self._parse_meta(soup, username)

        if not data.get("display_name"):
            return self._result(username, found=False, error="parse_failed")

        return CrawlerResult(
            platform=self.platform,
            identifier=username,
            found=True,
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    def _parse_meta(self, soup: BeautifulSoup, username: str) -> dict:
        data: dict = {"handle": username}
        try:
            title_tag = soup.find("meta", property="og:title")
            if title_tag and title_tag.get("content"):
                data["display_name"] = title_tag["content"].strip()

            image_tag = soup.find("meta", property="og:image")
            if image_tag and image_tag.get("content"):
                data["avatar_url"] = image_tag["content"].strip()

            desc_tag = soup.find("meta", property="og:description")
            if desc_tag and desc_tag.get("content"):
                desc = desc_tag["content"].strip()
                data["bio"] = desc[:500]
                m = FOLLOWER_RE.search(desc)
                if m:
                    raw = m.group(1).replace(",", "")
                    try:
                        data["follower_count"] = int(raw)
                    except ValueError:  # pragma: no cover
                        pass

        except Exception as exc:
            logger.debug("Pinterest parse error: %s", exc)
        return data
