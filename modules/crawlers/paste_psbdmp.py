"""
paste_psbdmp.py — psbdmp.ws Pastebin dump aggregator search.

psbdmp.ws indexes Pastebin content and exposes a JSON search API.
Results include paste IDs, timestamps, and text snippets. Full paste
content is accessible at pastebin.com/raw/{id}.

Registered as "paste_psbdmp".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.flaresolverr_base import FlareSolverrCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_PSBDMP_API_URL = "https://psbdmp.ws/api/v3/search/{query}"
_PASTEBIN_RAW_URL = "https://pastebin.com/raw/{paste_id}"


def _parse_psbdmp_response(data: list[dict]) -> list[dict]:
    """
    Convert psbdmp API response items into normalised mention records.

    Each API item contains:
    - id:   Pastebin paste ID
    - time: Unix timestamp (string or int)
    - text: short snippet of the paste content
    """
    mentions: list[dict] = []
    for item in data:
        paste_id = item.get("id", "")
        if not paste_id:
            continue

        mentions.append(
            {
                "pastebin_id": paste_id,
                "url": _PASTEBIN_RAW_URL.format(paste_id=paste_id),
                "time": str(item.get("time", "")),
                "preview": item.get("text", "")[:300],
            }
        )

    return mentions


@register("paste_psbdmp")
class PastePsbdmpCrawler(FlareSolverrCrawler):
    """
    Searches psbdmp.ws for Pastebin pastes mentioning an identifier.

    psbdmp.ws provides a free JSON API that indexes publicly accessible
    Pastebin content. Routes through TOR2 for attribution protection.

    identifier: email, username, keyword, or domain
    """

    platform = "paste_psbdmp"
    source_reliability = 0.35
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded_query = quote_plus(query)
        url = _PSBDMP_API_URL.format(query=encoded_query)

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

        if response.status_code == 404:
            # psbdmp returns 404 when no results found
            return self._result(
                identifier,
                found=False,
                mentions=[],
                query=query,
                mention_count=0,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        # psbdmp can return either a list directly or {"data": [...]}
        if isinstance(data, dict):
            items = data.get("data", data.get("results", []))
        elif isinstance(data, list):
            items = data
        else:
            items = []

        mentions = _parse_psbdmp_response(items)

        return self._result(
            identifier,
            found=len(mentions) > 0,
            mentions=mentions,
            query=query,
            mention_count=len(mentions),
        )
