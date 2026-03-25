"""
ancestry_hints.py — Ancestry.com hint search crawler.

Searches the Ancestry public search endpoint for person records by name.
Returns family hints including parents, children, spouses and siblings where
available from public-facing result data.

Registered as "ancestry_hints".
"""

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

SOURCE_RELIABILITY = 0.65
_SEARCH_URL = "https://www.ancestry.com/search/?name={first}_{last}"


def _parse_hints(data: dict) -> dict:
    """Extract standardised genealogy fields from Ancestry search JSON."""
    results = data.get("results", [])
    if not results:
        return {}

    top = results[0]
    person_name = top.get("name") or top.get("title", "")
    facts = top.get("facts", {})

    parents = [{"name": p.get("name", ""), "birth_year": None} for p in top.get("parents", [])]
    children = [{"name": c.get("name", ""), "birth_year": None} for c in top.get("children", [])]
    spouses = [
        {"name": s.get("name", ""), "marriage_date": s.get("marriage_date")}
        for s in top.get("spouses", [])
    ]
    siblings = [{"name": s.get("name", ""), "birth_year": None} for s in top.get("siblings", [])]

    return {
        "person_name": person_name,
        "birth_date": facts.get("birth_date"),
        "birth_place": facts.get("birth_place"),
        "death_date": facts.get("death_date"),
        "death_place": facts.get("death_place"),
        "parents": parents,
        "children": children,
        "spouses": spouses,
        "siblings": siblings,
        "source_url": top.get("url", ""),
        "record_type": "tree",
    }


@register("ancestry_hints")
class AncestryHintsCrawler(HttpxCrawler):
    """
    Searches Ancestry.com for genealogy hints.

    identifier: "First Last"

    source_reliability: 0.65 — crowdsourced trees, moderate quality.
    """

    platform = "ancestry_hints"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split(" ", 1)
        first = quote_plus(parts[0])
        last = quote_plus(parts[1]) if len(parts) > 1 else ""
        url = _SEARCH_URL.format(first=first, last=last)

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
            # Ancestry returns HTML for most requests; treat as not-found
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        parsed = _parse_hints(json_data)
        found = bool(parsed)

        # Ensure source_url from parsed doesn't conflict — prefer the request URL
        if parsed:
            parsed["source_url"] = url

        return self._result(
            identifier,
            found=found,
            **parsed,
            query=identifier,
        )
