"""
darkweb_torch.py — Torch .onion search engine crawler.

Torch is one of the oldest dark web search engines, accessible only via Tor.
This crawler connects through TOR3 (port 9054) to query the Torch onion and
parse search results.

Registered as "darkweb_torch".
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

_TORCH_URL = (
    "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5ayieeo2through7vlpa3ad.onion"
    "/4a1f6b371c/search.cgi?cmd=Search&q={query}&Submit=Search&pg={page}"
)
_MAX_RESULTS = 20


def _parse_torch_html(html: str) -> list[dict]:
    """
    Parse Torch search result HTML into structured records.

    Torch uses a classic directory listing format:
    - <dt> contains an <a href> link with the title
    - <dd> contains the description snippet
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    dt_tags = soup.find_all("dt")
    dd_tags = soup.find_all("dd")

    for i, dt in enumerate(dt_tags):
        a_tag = dt.find("a", href=True)
        if not a_tag:
            continue

        onion_url = a_tag.get("href", "").strip()
        title = a_tag.get_text(strip=True)
        description = ""

        if i < len(dd_tags):
            description = dd_tags[i].get_text(strip=True)

        if onion_url:
            results.append(
                {
                    "title": title,
                    "onion_url": onion_url,
                    "description": description,
                }
            )

    return results


@register("darkweb_torch")
class DarkwebTorchCrawler(HttpxCrawler):
    """
    Queries the Torch .onion search engine for a given search term.

    Requires a live TOR3 connection — Torch is only reachable via the Tor
    network. The SOCKS5 proxy at tor3_socks (port 9054) is used.

    identifier: freeform search query
    """

    platform = "darkweb_torch"
    source_reliability = 0.35
    requires_tor = True
    tor_instance = TorInstance.TOR3

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded_query = quote_plus(query)
        collected: list[dict] = []

        for page in range(1, 3):  # pages 1 and 2 → up to ~20 results
            if len(collected) >= _MAX_RESULTS:
                break

            url = _TORCH_URL.format(query=encoded_query, page=page)
            response = await self.get(url)

            if response is None:
                if page == 1:
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=identifier,
                        found=False,
                        error="http_error",
                        source_reliability=self.source_reliability,
                    )
                break

            if response.status_code != 200:
                if page == 1:
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=identifier,
                        found=False,
                        error=f"http_{response.status_code}",
                        source_reliability=self.source_reliability,
                    )
                break

            page_results = _parse_torch_html(response.text)
            if not page_results:
                break

            collected.extend(page_results)

        collected = collected[:_MAX_RESULTS]

        return self._result(
            identifier,
            found=len(collected) > 0,
            results=collected,
            query=query,
            result_count=len(collected),
        )
