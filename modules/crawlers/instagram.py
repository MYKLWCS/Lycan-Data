from __future__ import annotations
import logging
import re

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY

logger = logging.getLogger(__name__)


@register("instagram")
class InstagramCrawler(PlaywrightCrawler):
    """Scrapes public Instagram profiles without authentication."""

    platform = "instagram"
    source_reliability = SOURCE_RELIABILITY.get("instagram", 0.55)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@").lower()
        url = f"https://www.instagram.com/{handle}/"

        async with self.page(url) as page:
            content = await page.content()

            if "Sorry, this page" in content or "isn't available" in content:
                return self._result(handle, found=False, handle=handle)

            if "This Account is Private" in content or "This account is private" in content:
                return self._result(handle, found=True, handle=handle, is_private=True)

            data = await self._extract_profile(page, handle)

            if not data.get("display_name") and not data.get("follower_count"):
                await self.rotate_circuit()
                return self._result(handle, found=False, error="blocked_or_captcha", handle=handle)

        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=True,
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    async def _extract_profile(self, page, handle: str) -> dict:
        data: dict = {"handle": handle}
        try:
            meta_desc = await page.get_attribute('meta[name="description"]', "content") or ""
            follower_match = re.search(r"([\d,\.]+[KMB]?)\s+Followers", meta_desc, re.IGNORECASE)
            following_match = re.search(r"([\d,\.]+[KMB]?)\s+Following", meta_desc, re.IGNORECASE)
            post_match = re.search(r"([\d,\.]+[KMB]?)\s+Posts", meta_desc, re.IGNORECASE)

            if follower_match:
                data["follower_count"] = _parse_count(follower_match.group(1))
            if following_match:
                data["following_count"] = _parse_count(following_match.group(1))
            if post_match:
                data["post_count"] = _parse_count(post_match.group(1))

            # Title format: "username (@handle) • Instagram photos and videos"
            title = await page.title() or ""
            if "•" in title:
                data["display_name"] = title.split("•")[0].strip()

            og_desc = await page.get_attribute('meta[property="og:description"]', "content") or ""
            if og_desc:
                data["bio"] = og_desc[:500]

            content = await page.content()
            data["is_verified"] = "is_verified\":true" in content or '"verified":true' in content

        except Exception as exc:
            logger.debug("Instagram extract error: %s", exc)
        return data


def _parse_count(s: str) -> int | None:
    """Parse '1.5M', '12.3K', '1,234' to int."""
    s = s.replace(",", "").strip()
    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if s.lower().endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                return None
    try:
        return int(s)
    except ValueError:
        return None
