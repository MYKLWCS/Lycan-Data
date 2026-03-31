from __future__ import annotations

import logging
import re

import httpx

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from shared.constants import SOURCE_RELIABILITY

logger = logging.getLogger(__name__)


@register("facebook")
class FacebookCrawler(PlaywrightCrawler):
    """Scrapes public Facebook profiles via mobile site."""

    platform = "facebook"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = SOURCE_RELIABILITY.get("facebook", 0.60)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@").rstrip("/")
        url = f"https://m.facebook.com/{handle}"

        async with self.page(url) as page:
            content = await page.content()

            if "log in" in content.lower() and "password" in content.lower():
                return await self._try_graph(handle)

            if "page not found" in content.lower() or "content not found" in content.lower():
                return self._result(handle, found=False, handle=handle)

            data = await self._extract_mobile(page, handle, content)

        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=bool(data.get("display_name") or data.get("handle")),
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    async def _extract_mobile(self, page, handle: str, content: str) -> dict:
        data: dict = {"handle": handle}
        try:
            title = await page.title() or ""
            if title and "Facebook" in title:
                data["display_name"] = title.replace("| Facebook", "").replace("- Home", "").strip()

            about_elem = await page.query_selector('[data-key="bio"]')
            if about_elem:
                data["bio"] = (await about_elem.inner_text())[:500]

            followers_match = re.search(
                r"([\d,\.]+[KMB]?)\s+(?:followers|likes)", content, re.IGNORECASE
            )
            if followers_match:
                from modules.crawlers.instagram import _parse_count

                data["follower_count"] = _parse_count(followers_match.group(1))

            loc_match = re.search(r'"location":\s*"([^"]+)"', content)
            if loc_match:
                data["location"] = loc_match.group(1)

        except Exception as exc:
            logger.debug("Facebook extract error: %s", exc)
        return data

    async def _try_graph(self, handle: str) -> CrawlerResult:
        """Fall back: try the public Open Graph endpoint."""
        url = f"https://graph.facebook.com/{handle}?fields=name,about,fan_count,category"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    j = r.json()
                    if "name" in j:
                        return CrawlerResult(
                            platform=self.platform,
                            identifier=handle,
                            found=True,
                            data={
                                "handle": handle,
                                "display_name": j.get("name"),
                                "bio": j.get("about"),
                                "follower_count": j.get("fan_count"),
                            },
                            profile_url=f"https://facebook.com/{handle}",
                            source_reliability=self.source_reliability,
                        )
        except Exception:
            logger.debug("Facebook Graph metadata probe failed for %s", handle, exc_info=True)
        return self._result(handle, found=False, handle=handle, error="login_wall")
