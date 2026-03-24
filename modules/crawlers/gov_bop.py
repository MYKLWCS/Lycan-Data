"""
gov_bop.py — Federal Bureau of Prisons inmate locator.

Queries the BOP public inmate locator for federal inmate records by name.
Returns a raw HTML preview since BOP does not expose a structured JSON API.

Registered as "gov_bop".
"""
from __future__ import annotations

import logging
import re
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_URL = "https://www.bop.gov/inmateloc/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://www.bop.gov/inmateloc/",
    "Origin": "https://www.bop.gov",
}

_NO_RECORDS_PHRASES = [
    "No records found",
    "no records found",
    "Your search did not return any results",
    "did not return any results",
]

_REGISTER_RE = re.compile(r"<td[^>]*>(\d{8})</td>")


def _extract_register_numbers(html: str) -> list[str]:
    """Pull 8-digit BOP register numbers from HTML table cells."""
    return _REGISTER_RE.findall(html)


def _response_is_empty(text: str) -> bool:
    """Return True when the BOP response explicitly signals no results."""
    for phrase in _NO_RECORDS_PHRASES:
        if phrase in text:
            return True
    return False


@register("gov_bop")
class BopCrawler(HttpxCrawler):
    """
    Queries the Federal Bureau of Prisons inmate locator.

    identifier: inmate name (e.g. "John Smith")

    Note: BOP does not expose a structured JSON API. The response is HTML.
    The raw_response_preview field contains the first 2000 characters for
    downstream HTML parsing. Extracted register numbers are also included
    when present.

    Data keys returned:
        query                 — the original search term
        raw_response_preview  — first 2000 chars of BOP HTML response
        register_numbers      — list of 8-digit register numbers found in HTML
        note                  — usage guidance for callers
    """

    platform = "gov_bop"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        params: dict[str, Any] = {
            "todo": "query",
            "output": "HTML",
            "namesearch": query,
        }

        resp = await self.post(_URL, data=params, headers=_HEADERS)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                query=query,
                raw_response_preview="",
                register_numbers=[],
                note="Parse HTML response for inmate records",
            )

        response_text: str = resp.text if resp else ""
        preview: str = response_text[:2000]
        register_numbers = _extract_register_numbers(response_text)
        found = bool(response_text) and not _response_is_empty(response_text)

        return self._result(
            identifier,
            found=found,
            query=query,
            raw_response_preview=preview,
            register_numbers=register_numbers,
            note="Parse HTML response for inmate records",
        )
