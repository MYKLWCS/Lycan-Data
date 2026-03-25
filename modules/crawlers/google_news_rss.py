"""
google_news_rss.py — Google News RSS feed crawler.

Fetches Google News RSS for a person's name mentions.
Registered as "google_news_rss".
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


@register("google_news_rss")
class GoogleNewsRssCrawler(HttpxCrawler):
    """
    Fetches Google News RSS feed for a person's name.
    identifier: full name (e.g. "John Doe")
    """

    platform = "google_news_rss"
    SOURCE_RELIABILITY = 0.60
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
            logger.debug("Google News RSS parse error for %s: %s", identifier, exc)
            return self._result(identifier, found=False, error="parse_error")

        articles = []
        for item in root.findall(".//item")[:20]:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            source_el = item.find("source")
            title = title_el.text if title_el is not None else ""
            if title:
                articles.append(
                    {
                        "title": title,
                        "url": link_el.text if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                        "source": source_el.text if source_el is not None else "",
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
