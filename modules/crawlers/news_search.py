"""
News Search crawler — searches multiple free news sources for mentions of a
person or company. Aggregates results from DuckDuckGo News, Google News RSS,
and Bing News RSS.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

# ── Article tagging keywords ───────────────────────────────────────────────────

ARTICLE_TAGS: dict[str, list[str]] = {
    "legal": [
        "lawsuit",
        "sued",
        "court",
        "judge",
        "verdict",
        "settlement",
        "attorney",
        "lawyer",
        "indicted",
    ],
    "financial": [
        "bankruptcy",
        "fraud",
        "sec",
        "fine",
        "penalty",
        "ipo",
        "funding",
        "acquisition",
    ],
    "criminal": [
        "arrested",
        "charged",
        "convicted",
        "prison",
        "jail",
        "sentence",
        "criminal",
    ],
    "obituary": [
        "died",
        "passed away",
        "death",
        "funeral",
        "obituary",
        "in memoriam",
    ],
    "corporate": [
        "ceo",
        "founder",
        "appointed",
        "resigned",
        "merger",
        "company",
        "startup",
    ],
}


def _tag_article(title: str, snippet: str) -> list[str]:
    """Return category tags based on keywords found in title or snippet."""
    text = (title + " " + snippet).lower()
    tags: list[str] = []
    for category, keywords in ARTICLE_TAGS.items():
        if any(kw in text for kw in keywords):
            tags.append(category)
    if not tags:
        tags.append("general")
    return tags


@register("news_search")
class NewsSearchCrawler(CurlCrawler):
    """
    Searches DuckDuckGo News, Google News RSS, and Bing News RSS for mentions
    of a person or company name.

    identifier format: free-text query, e.g. "John Smith CEO fraud"
    """

    platform = "news_search"
    source_reliability = 0.55
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        articles: list[dict] = []
        seen_urls: set[str] = set()

        # ── DuckDuckGo News HTML ───────────────────────────────────────────────
        ddg_articles = await self._scrape_ddg(query)
        for art in ddg_articles:
            url = art.get("url", "")
            if url and url not in seen_urls:  # pragma: no branch
                seen_urls.add(url)
                articles.append(art)

        # ── Google News RSS ────────────────────────────────────────────────────
        gnews_articles = await self._scrape_google_news_rss(query)
        for art in gnews_articles:
            url = art.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                articles.append(art)

        # ── Bing News RSS ──────────────────────────────────────────────────────
        bing_articles = await self._scrape_bing_rss(query)
        for art in bing_articles:
            url = art.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                articles.append(art)

        return self._result(
            identifier=identifier,
            found=True,
            articles=articles,
            query=query,
            article_count=len(articles),
        )

    # ── DuckDuckGo News ────────────────────────────────────────────────────────

    async def _scrape_ddg(self, query: str) -> list[dict]:
        encoded = quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}&ia=news"
        response = await self.get(url, headers={"Accept-Language": "en-US,en;q=0.9"})
        if not response or response.status_code != 200:
            logger.warning("DuckDuckGo News request failed for query: %s", query)
            return []
        return _parse_ddg_html(response.text)

    # ── Google News RSS ────────────────────────────────────────────────────────

    async def _scrape_google_news_rss(self, query: str) -> list[dict]:
        encoded = quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=US&ceid=US:en"
        response = await self.get(url)
        if not response or response.status_code != 200:
            logger.warning("Google News RSS request failed for query: %s", query)
            return []
        return _parse_rss(response.text, source="google_news")

    # ── Bing News RSS ──────────────────────────────────────────────────────────

    async def _scrape_bing_rss(self, query: str) -> list[dict]:
        encoded = quote_plus(query)
        url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
        response = await self.get(url)
        if not response or response.status_code != 200:
            logger.warning("Bing News RSS request failed for query: %s", query)
            return []
        return _parse_rss(response.text, source="bing_news")


# ── Parsers ────────────────────────────────────────────────────────────────────


def _parse_ddg_html(html: str) -> list[dict]:
    """Parse DuckDuckGo HTML search results for news articles."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    # DDG result divs have class "result"
    result_divs = soup.find_all("div", class_="result")
    if not result_divs:
        # Broader fallback
        result_divs = soup.find_all("div", class_=lambda c: c and "result" in c)

    for div in result_divs[:20]:
        article = _extract_ddg_result(div)
        if article:
            results.append(article)

    return results


def _extract_ddg_result(div) -> dict | None:
    """Extract a single article dict from a DDG result div."""
    try:
        # Title + URL
        link_el = div.find("a", class_="result__a") or div.find("a")
        if not link_el:
            return None
        title = link_el.get_text(strip=True)
        url = link_el.get("href", "")

        # Snippet
        snippet_el = div.find(class_=lambda c: c and "snippet" in c if c else False)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        # Date — DDG sometimes embeds it in the result
        date_el = div.find(class_=lambda c: c and ("date" in c or "time" in c) if c else False)
        date = date_el.get_text(strip=True) if date_el else ""

        if not title or not url:
            return None

        categories = _tag_article(title, snippet)
        return {
            "title": title,
            "url": url,
            "date": date,
            "source": "duckduckgo_news",
            "snippet": snippet,
            "categories": categories,
        }
    except Exception as exc:
        logger.debug("DDG result parse error: %s", exc)
        return None


def _parse_rss(xml_text: str, source: str) -> list[dict]:
    """Parse an RSS feed and extract <item> elements as articles."""
    results: list[dict] = []
    try:
        root = ElementTree.fromstring(xml_text)  # nosec B314 — RSS feeds from known services
    except ElementTree.ParseError as exc:
        logger.warning("RSS parse error (%s): %s", source, exc)
        return results

    # Handle namespace stripping
    re.compile(r"\{[^}]*\}")
    channel = root.find("channel")
    if channel is None:
        # Some feeds put items directly under root
        items = root.findall("item")
    else:
        items = channel.findall("item")

    for item in items[:20]:

        def _text(tag: str) -> str:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        title = _text("title")
        url = _text("link")
        date = _text("pubDate")
        snippet = _text("description")

        if not title:
            continue

        # Strip HTML tags from snippet
        if snippet:
            snippet = BeautifulSoup(snippet, "html.parser").get_text(strip=True)

        categories = _tag_article(title, snippet)
        results.append(
            {
                "title": title,
                "url": url,
                "date": date,
                "source": source,
                "snippet": snippet,
                "categories": categories,
            }
        )

    return results
