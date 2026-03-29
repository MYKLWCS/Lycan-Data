from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("youtube")
class YouTubeCrawler(HttpxCrawler):
    """Scrapes public YouTube channel pages."""

    platform = "youtube"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = SOURCE_RELIABILITY.get("twitter", 0.55)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@")
        # Try @handle format first (modern), then /c/ and /channel/ fallbacks
        for url_template in [
            f"https://www.youtube.com/@{handle}",
            f"https://www.youtube.com/c/{handle}",
            f"https://www.youtube.com/user/{handle}",
        ]:
            result = await self._try_url(url_template, handle)
            if result.found:
                return result

        return self._result(handle, found=False, handle=handle)

    async def _try_url(self, url: str, handle: str) -> CrawlerResult:
        response = await self.get(url)
        if response is None or response.status_code != 200:
            return self._result(handle, found=False)
        if "uxe=" in str(response.url) or "error" in str(response.url).lower():
            return self._result(handle, found=False)

        data = self._parse(response.text, handle)
        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=bool(data.get("display_name")),
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    # Consent / GDPR interstitial page markers (multilingual)
    _CONSENT_MARKERS = [
        "before you continue",
        "bevor sie zu youtube",
        "avant de continuer",
        "innan du fortsätter",
        "antes de continuar",
        "prima di continuare",
        "voordat je verdergaat",
        "zanim przejdziesz",
        "прежде чем продолжить",
        "consent",
        "cookie",
        "gdpr",
    ]

    def _parse(self, html: str, handle: str) -> dict:
        data: dict = {"handle": handle}
        soup = BeautifulSoup(html, "html.parser")

        # Channel name from title
        title_tag = soup.find("title")
        if title_tag:
            t = title_tag.get_text(strip=True)
            # Reject consent/GDPR interstitial pages
            t_lower = t.lower()
            if any(marker in t_lower for marker in self._CONSENT_MARKERS):
                return data  # empty — will cause found=False
            data["display_name"] = t.replace(" - YouTube", "").strip()

        # Description from meta
        desc = soup.find("meta", {"name": "description"})
        if desc:
            data["bio"] = desc.get("content", "")[:500]

        # Subscriber count in ytInitialData JSON
        sub_match = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"', html)
        if sub_match:
            data["subscriber_count_text"] = sub_match.group(1)

        # Video count
        video_match = re.search(r'"videoCountText":\{"runs":\[\{"text":"(\d+)"', html)
        if video_match:
            data["post_count"] = int(video_match.group(1))

        # Country
        country_match = re.search(r'"country":\{"simpleText":"([^"]+)"', html)
        if country_match:
            data["location"] = country_match.group(1)

        return data
