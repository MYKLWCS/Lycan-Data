"""
paste_ghostbin.py — Rentry.co paste site search.

Ghostbin went offline. This module targets rentry.co, a minimalist
paste and document site with a search endpoint.

Registered as "paste_ghostbin".
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

_RENTRY_SEARCH_URL = "https://rentry.co/search?q={query}"
_RENTRY_BASE = "https://rentry.co"


def _parse_rentry_html(html: str) -> list[dict]:
    """
    Parse rentry.co search results HTML.

    Results appear as list items or article elements containing links and
    a short content preview.
    """
    soup = BeautifulSoup(html, "html.parser")
    mentions: list[dict] = []

    # rentry.co search returns a list of matching pages
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()

        # Filter to actual paste paths (e.g. /abcde)
        if not href.startswith("/") or len(href) < 3 or "/" in href[1:]:
            continue

        # Skip navigation links
        slug = href.lstrip("/")
        if slug in ("search", "new", "login", "register", "api"):
            continue

        url = f"{_RENTRY_BASE}{href}"
        title = a_tag.get_text(strip=True) or slug

        # Try to get nearby text as preview
        parent = a_tag.parent
        preview = ""
        if parent:
            sibling_text = parent.get_text(strip=True)
            if sibling_text and sibling_text != title:
                preview = sibling_text[:200]

        mentions.append(
            {
                "title": title,
                "url": url,
                "preview": preview,
            }
        )

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for m in mentions:
        if m["url"] not in seen:
            seen.add(m["url"])
            unique.append(m)

    return unique


@register("paste_ghostbin")
class PasteGhostbinCrawler(FlareSolverrCrawler):
    """
    Searches rentry.co for public pastes mentioning an identifier.

    (Ghostbin is offline; this module uses rentry.co as a replacement.)
    Routes through TOR2 for attribution protection.

    identifier: email, username, keyword
    """

    platform = "paste_ghostbin"
    source_reliability = 0.30
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded_query = quote_plus(query)
        url = _RENTRY_SEARCH_URL.format(query=encoded_query)

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

        mentions = _parse_rentry_html(response.text)

        return self._result(
            identifier,
            found=len(mentions) > 0,
            mentions=mentions,
            query=query,
            mention_count=len(mentions),
        )
