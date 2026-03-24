"""
darkweb_ahmia.py — Ahmia.fi clearnet search engine for .onion sites.

Ahmia indexes dark web content and exposes it via a clearnet interface,
making it searchable without a running Tor browser. This crawler queries
Ahmia and parses the resulting .onion URLs and metadata.

Registered as "darkweb_ahmia".
"""
from __future__ import annotations
import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_AHMIA_URL = "https://ahmia.fi/search/?q={query}&page={page}"
_MAX_RESULTS = 20


def _parse_ahmia_html(html: str) -> list[dict]:
    """
    Parse Ahmia search result HTML into structured records.

    Each result is wrapped in <li class="result"> and contains:
    - <h4>  — page title
    - <cite> — the .onion URL
    - <p>   — description snippet
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for li in soup.find_all("li", class_="result"):
        h4 = li.find("h4")
        cite = li.find("cite")
        p = li.find("p")

        title = h4.get_text(strip=True) if h4 else ""
        onion_url = cite.get_text(strip=True) if cite else ""
        description = p.get_text(strip=True) if p else ""

        if onion_url:
            results.append(
                {
                    "title": title,
                    "onion_url": onion_url,
                    "description": description,
                }
            )

    return results


@register("darkweb_ahmia")
class DarkwebAhmiaCrawler(HttpxCrawler):
    """
    Searches Ahmia.fi (clearnet) for .onion resources matching a query.

    Ahmia is a legitimate dark web search index accessible without Tor.
    We still route through TOR2 to avoid attribution of the search query
    to the investigator's IP.

    identifier: freeform search query (name, email, keyword, etc.)
    """

    platform = "darkweb_ahmia"
    source_reliability = 0.40
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded_query = quote_plus(query)
        collected: list[dict] = []

        for page in range(0, 2):  # page 0 and page 1 → up to ~20 results
            if len(collected) >= _MAX_RESULTS:
                break

            url = _AHMIA_URL.format(query=encoded_query, page=page)
            response = await self.get(url)

            if response is None:
                if page == 0:
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=identifier,
                        found=False,
                        error="http_error",
                        source_reliability=self.source_reliability,
                    )
                break

            if response.status_code == 429:
                logger.warning("Ahmia rate-limited on page %d", page)
                break

            if response.status_code != 200:
                if page == 0:
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=identifier,
                        found=False,
                        error=f"http_{response.status_code}",
                        source_reliability=self.source_reliability,
                    )
                break

            page_results = _parse_ahmia_html(response.text)
            if not page_results:
                break  # no more results

            collected.extend(page_results)

        collected = collected[:_MAX_RESULTS]

        return self._result(
            identifier,
            found=len(collected) > 0,
            results=collected,
            query=query,
            result_count=len(collected),
        )
