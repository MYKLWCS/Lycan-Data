"""
people_findagrave.py — FindAGrave memorial search crawler.

Searches FindAGrave.com for burial records, death dates, and family
connections for a given person name.

FindAGrave uses a public search endpoint that returns JSON when queried
with the appropriate headers and parameters.

Source: https://www.findagrave.com/memorial/search
Registered as "people_findagrave".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://www.findagrave.com/memorial/search"
    "?q={query}&firstname={first}&lastname={last}"
    "&memorialtype=person"
)
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
}

# JSON endpoint for ajax-based search
_JSON_URL = (
    "https://www.findagrave.com/memorial/search"
    "?q={query}&firstname={first}&lastname={last}"
    "&typeId=1"
)
_JSON_HEADERS = {
    **_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def _parse_memorial_html(html: str) -> list[dict[str, Any]]:
    """
    Extract memorial records from FindAGrave HTML search results.
    Looks for memorial card data embedded in the page.
    """
    results: list[dict[str, Any]] = []

    # FindAGrave encodes results as structured HTML blocks.
    # Each memorial has an id like "sr-{memorialId}" and contains name/dates.
    memorial_pattern = re.compile(
        r'<div[^>]+class="[^"]*memorial-item[^"]*"[^>]*>(.*?)</div\s*>',
        re.IGNORECASE | re.DOTALL,
    )
    name_pattern = re.compile(r'<a[^>]+href="/memorial/(\d+)/[^"]*"[^>]*>(.*?)</a>', re.IGNORECASE)
    date_pattern = re.compile(r"(\d{1,2}\s+\w+\s+\d{4}|\d{4})", re.IGNORECASE)

    def strip_tags(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s).strip()

    for block in memorial_pattern.finditer(html):
        block_text = block.group(1)
        name_match = name_pattern.search(block_text)
        if not name_match:
            continue
        memorial_id = name_match.group(1)
        name = strip_tags(name_match.group(2))
        dates = date_pattern.findall(block_text)

        results.append(
            {
                "memorial_id": memorial_id,
                "name": name,
                "dates": dates[:4],  # birth/death dates
                "memorial_url": f"https://www.findagrave.com/memorial/{memorial_id}",
            }
        )

    # Fallback: look for JSON-LD structured data
    if not results:
        jsonld_pattern = re.compile(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            re.IGNORECASE | re.DOTALL,
        )
        import json

        for match in jsonld_pattern.finditer(html):
            try:
                data = json.loads(match.group(1))
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Person":
                        results.append(
                            {
                                "memorial_id": "",
                                "name": item.get("name", ""),
                                "birth_date": item.get("birthDate", ""),
                                "death_date": item.get("deathDate", ""),
                                "memorial_url": item.get("url", ""),
                            }
                        )
            except Exception:
                continue

    return results[:20]


@register("people_findagrave")
class FindAGraveCrawler(HttpxCrawler):
    """
    Searches FindAGrave for burial/memorial records by full name.

    The identifier is split on the first space into first/last name
    for more precise search results.

    identifier: person name (e.g. "John Smith")

    Data keys returned:
        memorials   — list of matching memorial records (up to 20)
        total       — number of records found
        query       — the name searched
    """

    platform = "people_findagrave"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        full_name = identifier.strip()
        if not full_name:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                memorials=[],
                total=0,
                query=identifier,
            )

        parts = full_name.split(" ", 1)
        first = parts[0] if len(parts) >= 2 else ""
        last = parts[1] if len(parts) >= 2 else parts[0]

        url = _SEARCH_URL.format(
            query=quote_plus(full_name),
            first=quote_plus(first),
            last=quote_plus(last),
        )

        resp = await self.get(url, headers=_HEADERS)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                memorials=[],
                total=0,
                query=full_name,
            )

        if resp.status_code == 403:
            return self._result(
                identifier,
                found=False,
                error="blocked_403",
                memorials=[],
                total=0,
                query=full_name,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                memorials=[],
                total=0,
                query=full_name,
            )

        memorials = _parse_memorial_html(resp.text)
        return self._result(
            identifier,
            found=len(memorials) > 0,
            memorials=memorials,
            total=len(memorials),
            query=full_name,
        )
