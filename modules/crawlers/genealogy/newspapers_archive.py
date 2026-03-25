"""
newspapers_archive.py — Chronicling America newspaper archive crawler.

Searches the Library of Congress Chronicling America API for newspaper
mentions (obituaries, birth notices, marriage announcements) for a given
name.

Registered as "newspapers_archive".
"""

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

SOURCE_RELIABILITY = 0.75
_SEARCH_URL = (
    "https://chroniclingamerica.loc.gov/search/titles/results/"
    "?terms={name}&format=json"
)


def _parse_newspaper_result(data: dict) -> dict:
    """Extract genealogically relevant fields from Chronicling America response."""
    items = data.get("items", [])
    if not items:
        return {}

    top = items[0]
    title = top.get("title", "")
    place_of_publication = top.get("place_of_publication", "")

    return {
        "person_name": title,
        "birth_date": None,
        "birth_place": place_of_publication or None,
        "death_date": None,
        "death_place": None,
        "parents": [],
        "children": [],
        "spouses": [],
        "siblings": [],
        "source_url": top.get("url", ""),
        "record_type": "obituary",
    }


@register("newspapers_archive")
class NewspapersArchiveCrawler(HttpxCrawler):
    """
    Searches Chronicling America (loc.gov) for newspaper records.

    identifier: "First Last" — used as search terms.

    source_reliability: 0.75 — historical newspaper records, moderate-high quality.
    """

    platform = "newspapers_archive"
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = quote_plus(identifier.strip())
        url = _SEARCH_URL.format(name=name)

        response = await self.get(url, headers={"Accept": "application/json"})
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

        if response.status_code not in (200, 206):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        parsed = _parse_newspaper_result(json_data)
        found = bool(parsed)
        total = json_data.get("totalItems", len(json_data.get("items", [])))

        return self._result(
            identifier,
            found=found,
            total=total,
            query=identifier,
            **parsed,
        )
