"""
radaris.py — Radaris person profile crawler.

Scrapes radaris.com person profile pages.
Registered as "radaris".
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)


@register("radaris")
class RadarisCrawler(HttpxCrawler):
    """
    Scrapes Radaris person profile page.
    identifier: full name (e.g. "John Doe") — split into first/last for URL
    """

    platform = "radaris"
    SOURCE_RELIABILITY = 0.55
    source_reliability = SOURCE_RELIABILITY
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split()
        first = parts[0] if parts else identifier
        last = parts[-1] if len(parts) > 1 else ""
        slug = f"{first}-{last}".lower().replace(" ", "-")
        url = f"https://radaris.com/p/{slug}"

        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")
        name_tag = soup.find(class_="profile-name") or soup.find("h1")
        if not name_tag:
            return self._result(identifier, found=False)

        name_text = name_tag.get_text(strip=True)
        if not name_text or "not found" in name_text.lower():
            return self._result(identifier, found=False)

        addresses = []
        for addr in soup.find_all(class_="address")[:5]:
            addresses.append(addr.get_text(strip=True))

        age_tag = soup.find(class_="age") or soup.find(class_="birth-date")
        data = {
            "name": name_text,
            "addresses": addresses,
            "age": age_tag.get_text(strip=True) if age_tag else None,
        }
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=data,
            profile_url=url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
