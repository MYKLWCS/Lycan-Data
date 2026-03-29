"""
geni_public.py — Geni.com public tree search crawler.

Queries the Geni public API for person records by name. Returns basic
genealogy data from public family trees where available.

Registered as "geni_public".
"""

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

SOURCE_RELIABILITY = 0.60
_SEARCH_URL = "https://www.geni.com/api/search?q={name}&page=1"


def _parse_geni_result(data: dict) -> dict:
    """Extract genealogy fields from Geni search response."""
    results = data.get("results", [])
    if not results:
        return {}

    top = results[0]
    full_name = top.get("name") or top.get("display_name", "")
    birth_data = top.get("birth", {}) or {}
    death_data = top.get("death", {}) or {}

    unions = top.get("unions", []) or []
    spouses: list[dict] = []
    for union in unions:
        for partner in union.get("partners", []):
            partner_name = partner.get("name") or partner.get("display_name", "")
            if partner_name and partner_name != full_name:
                spouses.append({"name": partner_name, "marriage_date": None})

    parents: list[dict] = []
    for p in top.get("parents", []) or []:
        parent_name = p.get("name") or p.get("display_name", "")
        if parent_name:
            parents.append({"name": parent_name, "birth_year": None})

    children: list[dict] = []
    for c in top.get("children", []) or []:
        child_name = c.get("name") or c.get("display_name", "")
        if child_name:
            children.append({"name": child_name, "birth_year": None})

    siblings: list[dict] = []
    for s in top.get("siblings", []) or []:
        sibling_name = s.get("name") or s.get("display_name", "")
        if sibling_name and sibling_name != full_name:
            siblings.append({"name": sibling_name, "birth_year": None})

    return {
        "person_name": full_name,
        "birth_date": birth_data.get("date", {}).get("year")
        if isinstance(birth_data.get("date"), dict)
        else birth_data.get("date"),
        "birth_place": birth_data.get("location", {}).get("city")
        if isinstance(birth_data.get("location"), dict)
        else None,
        "death_date": death_data.get("date", {}).get("year")
        if isinstance(death_data.get("date"), dict)
        else death_data.get("date"),
        "death_place": death_data.get("location", {}).get("city")
        if isinstance(death_data.get("location"), dict)
        else None,
        "parents": parents,
        "children": children,
        "spouses": spouses,
        "siblings": siblings,
        "source_url": top.get("url", ""),
        "record_type": "tree",
    }


@register("geni_public")
class GeniPublicCrawler(HttpxCrawler):
    """
    Searches Geni.com public family trees for a person.

    identifier: "First Last"

    source_reliability: 0.60 — crowdsourced trees, lower reliability.
    """

    platform = "geni_public"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
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

        if response.status_code == 401:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="auth_required",
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

        parsed = _parse_geni_result(json_data)
        found = bool(parsed)
        total = json_data.get("total_count", len(json_data.get("results", [])))

        return self._result(
            identifier,
            found=found,
            total=total,
            query=identifier,
            **parsed,
        )
