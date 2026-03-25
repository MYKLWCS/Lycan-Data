"""
paste_pastebin.py — Pastebin search via pastebin.com/search.

Searches Pastebin for public pastes mentioning a given query. Parses the
HTML search results page rather than using the Pro API.

Registered as "paste_pastebin".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.flaresolverr_base import FlareSolverrCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_PASTEBIN_SEARCH_URL = "https://pastebin.com/search?q={query}"


def _parse_pastebin_html(html: str) -> list[dict]:
    """
    Parse Pastebin search results page.

    Each result is a <div class="search-result"> containing:
    - <a> with href (paste URL) and title text
    - date info in the markup
    - a text snippet preview
    """
    soup = BeautifulSoup(html, "html.parser")
    mentions: list[dict] = []

    for div in soup.find_all("div", class_="search-result"):
        a_tag = div.find("a", href=True)
        if not a_tag:
            continue

        href = a_tag.get("href", "").strip()
        title = a_tag.get_text(strip=True)

        # Absolute URL
        if href.startswith("/"):
            url = f"https://pastebin.com{href}"
        else:
            url = href

        # Date — look for a time element or span with date info
        date_tag = div.find("span", class_="date")
        if not date_tag:
            date_tag = div.find("time")
        date = date_tag.get_text(strip=True) if date_tag else ""

        # Preview snippet
        preview_tag = div.find("p")
        preview = preview_tag.get_text(strip=True) if preview_tag else ""

        if url:
            mentions.append(
                {
                    "title": title,
                    "url": url,
                    "date": date,
                    "preview": preview,
                }
            )

    return mentions


@register("paste_pastebin")
class PastePastebinCrawler(FlareSolverrCrawler):
    """
    Searches Pastebin.com for public pastes mentioning an identifier.

    Routes through TOR2 to prevent the search query being linked to the
    investigator's IP. Pastebin rate-limits heavily, so circuit rotation
    may be needed for repeated queries.

    identifier: email, username, domain, or freeform keyword
    """

    platform = "paste_pastebin"
    source_reliability = 0.35
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded_query = quote_plus(query)
        url = _PASTEBIN_SEARCH_URL.format(query=encoded_query)

        response = await self.get(url)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        mentions = _parse_pastebin_html(response.text)

        return self._result(
            identifier,
            found=len(mentions) > 0,
            mentions=mentions,
            query=query,
            mention_count=len(mentions),
        )
