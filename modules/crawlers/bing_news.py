"""
bing_news.py — Bing News RSS feed crawler.

Fetches Bing News RSS for a person's name mentions.
Registered as "bing_news".
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_RSS_URL = "https://www.bing.com/news/search?q={query}&format=RSS"


@register("bing_news")
class BingNewsCrawler(HttpxCrawler):
    """
    Fetches Bing News RSS feed for a person's name.
    identifier: full name (e.g. "John Doe")
    """

    platform = "bing_news"
    category = CrawlerCategory.NEWS_MEDIA
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    SOURCE_RELIABILITY = 0.55
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        url = _RSS_URL.format(query=quote_plus(query))
        resp = await self.get(url, headers={"Accept": "application/rss+xml, application/xml"})
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            logger.debug("Bing News RSS parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        articles = []
        for item in root.findall(".//item")[:20]:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            desc_el = item.find("description")
            title = title_el.text if title_el is not None else ""
            if title:
                articles.append(
                    {
                        "title": title,
                        "url": link_el.text if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                        "description": (desc_el.text or "")[:300] if desc_el is not None else "",
                    }
                )

        if not articles:
            return self._result(identifier, found=False)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"articles": articles, "count": len(articles)},
            profile_url=url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
