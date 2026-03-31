"""
people_fbi_wanted.py — FBI Most Wanted public API crawler.

Searches the FBI's public Wanted API for persons by name, returning physical
descriptors, aliases, charges, reward text, and the official wanted page URL.

Registered as "people_fbi_wanted".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_FBI_URL = "https://api.fbi.gov/wanted/v1/list?title={name}&pageSize=20&page=1"


def _parse_items(data: dict) -> list[dict[str, Any]]:
    """Extract wanted person fields from FBI API response."""
    items: list[dict[str, Any]] = []
    for item in data.get("items", [])[:20]:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "title": item.get("title"),
                "description": item.get("description"),
                "aliases": item.get("aliases") or [],
                "dates_of_birth_used": item.get("dates_of_birth_used") or [],
                "hair": item.get("hair"),
                "eyes": item.get("eyes"),
                "height_min": item.get("height_min"),
                "height_max": item.get("height_max"),
                "weight": item.get("weight"),
                "weight_max": item.get("weight_max"),
                "sex": item.get("sex"),
                "race": item.get("race"),
                "nationality": item.get("nationality"),
                "reward_text": item.get("reward_text"),
                "caution": item.get("caution"),
                "url": item.get("url"),
                "status": item.get("status"),
                "modified": item.get("modified"),
                "publication": item.get("publication"),
                "subjects": item.get("subjects") or [],
                "field_offices": item.get("field_offices") or [],
            }
        )
    return items


@register("people_fbi_wanted")
class FbiWantedCrawler(HttpxCrawler):
    """
    Searches the FBI Most Wanted public API by person name.

    The FBI API uses the 'title' field for name searches. Results include
    physical descriptors, aliases, charges, reward information, and links
    to the official FBI wanted poster page.

    identifier: person full name (e.g. "John Doe")

    Data keys returned:
        items   — list of wanted person records (up to 20)
        total   — total matching records reported by the API
    """

    platform = "people_fbi_wanted"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        url = _FBI_URL.format(name=encoded)
        resp = await self.get(url)

        if resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if resp.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if resp.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{resp.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            payload = resp.json()
            items = _parse_items(payload)
            total: int = payload.get("total", len(items))
        except Exception as exc:
            logger.warning("FBI Wanted JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(items) > 0,
            items=items,
            total=total,
        )
