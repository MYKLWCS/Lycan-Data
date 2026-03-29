"""
people_usmarshals.py — US Marshals Service Fugitive Search crawler.

Searches the USMS public fugitive list for a given name.
The USMS publishes a searchable fugitive database at usmarshals.gov.
This crawler fetches the public JSON endpoint for fugitive records.

Source: https://www.usmarshals.gov/investigations/most-wanted
API:    https://www.usmarshals.gov/api/v1/fugitives (GET, name param)
Fallback: HTML page scrape of the 15 Most Wanted list.
Registered as "people_usmarshals".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_USMS_API_URL = "https://www.usmarshals.gov/api/v1/fugitives?name={name}&limit=20"
_USMS_WANTED_URL = "https://www.usmarshals.gov/what-we-do/investigations/15-most-wanted"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; LycanBot/1.0)",
}


def _name_overlap_score(query: str, candidate: str) -> float:
    """Word-overlap match score 0.0–1.0."""
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & c_words) / len(q_words)


def _parse_fugitive_json(item: dict) -> dict[str, Any]:
    """Parse a single fugitive record from USMS JSON API."""
    return {
        "name": item.get("name", ""),
        "alias": item.get("alias", ""),
        "description": item.get("description", ""),
        "reward": item.get("reward", ""),
        "charges": item.get("charges", ""),
        "hair": item.get("hair", ""),
        "eyes": item.get("eyes", ""),
        "height": item.get("height", ""),
        "weight": item.get("weight", ""),
        "sex": item.get("sex", ""),
        "race": item.get("race", ""),
        "nationality": item.get("nationality", ""),
        "last_known_location": item.get("lastKnownLocation", ""),
        "caution": item.get("caution", ""),
        "details_url": item.get("url", ""),
    }


def _parse_html_page(html: str, query: str) -> list[dict[str, Any]]:
    """
    Parse USMS 15-most-wanted HTML page and filter by name query.
    Returns matching fugitive records extracted from HTML.
    """
    results: list[dict[str, Any]] = []
    # Extract basic card-like blocks — USMS page typically has h2/h3 for names
    name_pattern = re.compile(
        r"<(?:h2|h3)[^>]*>(.*?)</(?:h2|h3)>",
        re.IGNORECASE | re.DOTALL,
    )

    # Strip HTML tags for clean text
    def strip_tags(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s).strip()

    found_names = [strip_tags(m.group(1)) for m in name_pattern.finditer(html)]
    for name in found_names:
        if not name or len(name) < 3:
            continue
        score = _name_overlap_score(query, name)
        if score >= 0.5:
            results.append(
                {
                    "name": name,
                    "source": "usms_15_most_wanted",
                    "match_score": round(score, 3),
                    "details_url": _USMS_WANTED_URL,
                }
            )
    return results


@register("people_usmarshals")
class USMarshalsCrawler(HttpxCrawler):
    """
    Searches US Marshals Service fugitive records for a full name.

    Attempts the USMS JSON API first; falls back to scraping the
    15 Most Wanted HTML page if the API is unavailable.

    identifier: person name (e.g. "Alejandro Rosales Castillo")

    Data keys returned:
        fugitives   — list of matching fugitive records (up to 20)
        total       — count of matches found
        source      — "api" | "html_fallback"
        query       — the name searched
    """

    platform = "people_usmarshals"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        if not query:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                fugitives=[],
                total=0,
                source="",
                query=identifier,
            )

        # Try USMS JSON API first
        api_url = _USMS_API_URL.format(name=quote_plus(query))
        resp = await self.get(api_url, headers=_HEADERS)

        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
                raw = data if isinstance(data, list) else data.get("results", data.get("data", []))
                fugitives = [_parse_fugitive_json(item) for item in raw[:20]]
                # Filter by name match if we got more than needed
                if fugitives:
                    fugitives = [
                        f for f in fugitives if _name_overlap_score(query, f.get("name", "")) >= 0.3
                    ]
                return self._result(
                    identifier,
                    found=len(fugitives) > 0,
                    fugitives=fugitives,
                    total=len(fugitives),
                    source="api",
                    query=query,
                )
            except Exception as exc:
                logger.debug("USMS API parse failed, falling back to HTML: %s", exc)

        # Fallback: scrape the 15 Most Wanted page
        html_resp = await self.get(_USMS_WANTED_URL)
        if html_resp is None or html_resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                fugitives=[],
                total=0,
                source="",
                query=query,
            )

        fugitives = _parse_html_page(html_resp.text, query)
        return self._result(
            identifier,
            found=len(fugitives) > 0,
            fugitives=fugitives,
            total=len(fugitives),
            source="html_fallback",
            query=query,
        )
