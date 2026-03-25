from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

NOT_FOUND_SENTINEL = "This Snapcode is not available"


@register("snapchat")
class SnapchatCrawler(CurlCrawler):
    """Scrapes public Snapchat profiles via add page OG meta tags."""

    platform = "snapchat"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.45
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.lstrip("@").lower()
        url = f"https://www.snapchat.com/add/{username}"

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
                raw_title = title_tag["content"].strip()
                # Strip platform suffix in any language: "Name on Snapchat",
                # "Name sur Snapchat", "Name på Snapchat", etc.
                import re as _re

                clean = _re.sub(
                    r"\s+(on|sur|på|op|su|bei|na|en|の)\s+Snapchat\s*$",
                    "",
                    raw_title,
                    flags=_re.IGNORECASE,
                ).strip()
                # Also handle bare " Snapchat" at end
                clean = _re.sub(r"\s*[-–|]\s*Snapchat\s*$", "", clean, flags=_re.IGNORECASE).strip()
                # Reject if all that's left IS just the platform name
                if clean and clean.lower() != "snapchat":
                    data["display_name"] = clean

            image_tag = soup.find("meta", property="og:image")
            if image_tag and image_tag.get("content"):
                data["avatar_url"] = image_tag["content"].strip()
                data["snapcode_url"] = image_tag["content"].strip()

            desc_tag = soup.find("meta", property="og:description")
            if desc_tag and desc_tag.get("content"):
                data["bio"] = desc_tag["content"].strip()[:500]

        except Exception as exc:
            logger.debug("Snapchat parse error: %s", exc)
        return data
