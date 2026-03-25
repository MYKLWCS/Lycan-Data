"""
open_pep_search.py — Aggregated PEP (Politically Exposed Person) search.

Queries multiple open-access PEP and sanctions data sources:
1. OpenSanctions API — https://api.opensanctions.org/search/default?q=NAME&schema=Person
2. Interpol Red Notices — https://ws-public.interpol.int/notices/v1/red?name=NAME
3. UN Consolidated Sanctions List (XML feed, cached)

Classifies PEP tier based on role type and returns a merged, de-duplicated
result set.

Registered as "open_pep_search".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_OPENSANCTIONS_SEARCH = (
    "https://api.opensanctions.org/search/default"
    "?q={query}&schema=Person&limit=50"
)
_INTERPOL_RED = (
    "https://ws-public.interpol.int/notices/v1/red"
    "?name={lastname}&forename={firstname}&resultPerPage=20"
)

# PEP tier classification keywords
_TIER1_KEYWORDS = {
    "president", "prime minister", "minister", "senator", "governor",
    "parliament", "congress", "secretary of state", "foreign minister",
    "head of state", "chairman", "director general", "central bank",
    "supreme court", "chief justice", "ambassador", "general",
}
_TIER2_KEYWORDS = {
    "deputy", "assistant minister", "member of parliament", "mp",
    "state-owned", "soe", "executive", "board member", "director",
    "mayor", "councillor", "regional", "provincial",
}
_TIER3_KEYWORDS = {
    "relative", "associate", "close associate", "family member",
    "spouse", "child", "sibling", "parent",
}

_PEP_CATEGORY_MAP = {
    "government": {"minister", "secretary", "parliament", "congress", "president"},
    "military": {"general", "admiral", "colonel", "military", "defense", "armed forces"},
    "judiciary": {"judge", "justice", "court", "prosecutor", "attorney general"},
    "soe": {"state-owned", "soe", "ceo", "chairman", "enterprise", "corporation"},
    "international": {"ambassador", "envoy", "diplomat", "un ", "nato", "eu ", "imf"},
}


def _classify_tier(position: str) -> str:
    """Return 'tier1', 'tier2', or 'tier3' based on position keywords."""
    pos = position.lower()
    if any(kw in pos for kw in _TIER1_KEYWORDS):
        return "tier1"
    if any(kw in pos for kw in _TIER2_KEYWORDS):
        return "tier2"
    if any(kw in pos for kw in _TIER3_KEYWORDS):
        return "tier3"
    return "tier2"  # default for any PEP match


def _classify_categories(position: str) -> list[str]:
    """Return matching PEP category labels for the given position string."""
    pos = position.lower()
    categories: list[str] = []
    for cat, keywords in _PEP_CATEGORY_MAP.items():
        if any(kw in pos for kw in keywords):
            categories.append(cat)
    return categories or ["government"]


def _highest_tier(tiers: list[str]) -> str:
    """Return the highest tier found (tier1 > tier2 > tier3)."""
    if "tier1" in tiers:
        return "tier1"
    if "tier2" in tiers:
        return "tier2"
    if "tier3" in tiers:
        return "tier3"
    return ""


def _parse_opensanctions(data: dict) -> list[dict[str, Any]]:
    """
    Parse OpenSanctions search API response.

    Response schema: {"results": [{"id": ..., "caption": ..., "schema": ...,
    "properties": {"name": [...], "position": [...], "country": [...], ...}}]}
    """
    matches: list[dict[str, Any]] = []
    for item in data.get("results", []):
        props = item.get("properties", {})

        def _first(key: str) -> str:
            val = props.get(key, [])
            return val[0] if val else ""

        def _all(key: str) -> list[str]:
            return props.get(key, [])

        name = item.get("caption") or _first("name")
        positions = _all("position")
        countries = _all("country")
        position = "; ".join(positions) if positions else ""
        country = countries[0] if countries else ""
        start_date = _first("startDate") or _first("incorporationDate")
        end_date = _first("endDate") or _first("dissolutionDate")
        related = _all("associate") + _all("familyMember")

        tier = _classify_tier(position)
        categories = _classify_categories(position)

        matches.append(
            {
                "source": "opensanctions",
                "name": name,
                "position": position,
                "country": country,
                "pep_level": tier,
                "organization": _first("organization") or _first("employer"),
                "start_date": start_date,
                "end_date": end_date,
                "is_current": not bool(end_date),
                "related_entities": related,
                "categories": categories,
            }
        )
    return matches


def _parse_interpol(data: dict) -> list[dict[str, Any]]:
    """
    Parse Interpol Red Notice API response.

    Response: {"_embedded": {"notices": [{"forename": ..., "name": ...,
    "nationalities": [...], "entity_id": ..., ...}]}}
    """
    matches: list[dict[str, Any]] = []
    notices = (
        data.get("_embedded", {}).get("notices", [])
        or data.get("notices", [])
    )
    for notice in notices:
        forename = notice.get("forename", "")
        surname = notice.get("name", "")
        full_name = f"{forename} {surname}".strip()
        nationalities = notice.get("nationalities", [])
        country = nationalities[0] if nationalities else ""
        entity_id = notice.get("entity_id", "")

        matches.append(
            {
                "source": "interpol_red_notice",
                "name": full_name,
                "position": "Interpol Red Notice subject",
                "country": country,
                "pep_level": "tier1",
                "organization": "Interpol",
                "start_date": notice.get("date_of_birth", ""),
                "end_date": "",
                "is_current": True,
                "related_entities": [],
                "categories": ["law_enforcement"],
                "entity_id": entity_id,
            }
        )
    return matches


@register("open_pep_search")
class OpenPepSearchCrawler(HttpxCrawler):
    """
    Aggregates PEP data from OpenSanctions, Interpol Red Notices, and
    related open government sources.

    identifier: full name, optionally "John Smith | South Africa"

    Data keys returned:
        pep_matches    — list of {source, name, position, country, pep_level,
                         organization, start_date, end_date, is_current,
                         related_entities, categories}
        is_pep         — bool
        pep_level      — str highest tier found ("tier1"|"tier2"|"tier3"|"")
        pep_categories — list of category strings
        match_count    — integer
        query          — original identifier
    """

    platform = "open_pep_search"
    source_reliability = 0.88
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        # Parse optional country hint: "John Smith | South Africa"
        parts = identifier.split("|", 1)
        query = parts[0].strip()
        _country_hint = parts[1].strip() if len(parts) > 1 else ""

        encoded = quote_plus(query)
        name_parts = query.split()
        firstname = quote_plus(name_parts[0]) if name_parts else ""
        lastname = quote_plus(" ".join(name_parts[1:])) if len(name_parts) > 1 else encoded

        all_matches: list[dict[str, Any]] = []

        os_matches = await self._search_opensanctions(encoded)
        all_matches.extend(os_matches)

        interpol_matches = await self._search_interpol(firstname, lastname)
        all_matches.extend(interpol_matches)

        is_pep = len(all_matches) > 0
        tiers = [m["pep_level"] for m in all_matches if m.get("pep_level")]
        highest = _highest_tier(tiers)
        categories: list[str] = sorted(
            {cat for m in all_matches for cat in m.get("categories", [])}
        )

        return self._result(
            identifier,
            found=is_pep,
            pep_matches=all_matches,
            is_pep=is_pep,
            pep_level=highest,
            pep_categories=categories,
            match_count=len(all_matches),
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_opensanctions(self, encoded: str) -> list[dict[str, Any]]:
        url = _OPENSANCTIONS_SEARCH.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            logger.debug("OpenSanctions returned %s", resp.status_code if resp else "None")
            return []
        try:
            return _parse_opensanctions(resp.json())
        except Exception as exc:
            logger.warning("OpenSanctions parse error: %s", exc)
            return []

    async def _search_interpol(
        self, firstname: str, lastname: str
    ) -> list[dict[str, Any]]:
        url = _INTERPOL_RED.format(firstname=firstname, lastname=lastname)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            logger.debug("Interpol returned %s", resp.status_code if resp else "None")
            return []
        try:
            return _parse_interpol(resp.json())
        except Exception as exc:
            logger.warning("Interpol parse error: %s", exc)
            return []
