"""
clustrmaps.py — ClustrMaps person page crawler.

Scrapes clustrmaps.com for address history on a person.
Registered as "clustrmaps".
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)


@register("clustrmaps")
class ClustrMapsCrawler(HttpxCrawler):
    """
    Scrapes ClustrMaps person page for address history.
    identifier: full name (e.g. "John Doe")
    """

    platform = "clustrmaps"
    SOURCE_RELIABILITY = 0.50
    source_reliability = SOURCE_RELIABILITY
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split()
        first = parts[0] if parts else identifier
        last = parts[-1] if len(parts) > 1 else ""
        slug = f"{first}-{last}".lower().replace(" ", "-")
        url = f"https://clustrmaps.com/person/{slug}"

        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")
        name_tag = soup.find("h1")
        if not name_tag:
            return self._result(identifier, found=False)

        addresses = []
        for item in soup.find_all(class_="address-item")[:10]:
            text = item.get_text(strip=True)
            if text:
                addresses.append(text)

        if not addresses:
            for div in soup.find_all("div", class_=lambda c: c and "address" in c.lower())[:5]:
                text = div.get_text(strip=True)
                if text:
                    addresses.append(text)

        data = {
            "name": name_tag.get_text(strip=True),
            "addresses": addresses,
        }
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(addresses),
            data=data,
            profile_url=url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
