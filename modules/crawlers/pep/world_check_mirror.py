"""
world_check_mirror.py — World-Check style KYC/AML mirror search.

Searches publicly accessible KYC/AML aggregation sites that surface
World-Check style data profiles without requiring a subscription:
- ComplyAdvantage public entity search
- Dow Jones Risk & Compliance public profile lookup
- Acuris Risk Intelligence (public-facing search)

All results are normalised to the same schema as open_pep_search and
tagged with source="world_check_mirror".

Requires Tor/residential proxy to avoid IP-based rate limits on these
commercial-grade compliance portals.

Registered as "world_check_mirror".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# ComplyAdvantage public-facing search (no API key for basic entity search)
_COMPLY_ADVANTAGE_URL = (
    "https://app.complyadvantage.com/public/search?q={query}&types=person"
)
# Dow Jones Risk public profile directory
_DOW_JONES_URL = (
    "https://www.dowjones.com/risk/?q={query}"
)
# Acuris Risk Intelligence public search
_ACURIS_URL = (
    "https://www.acuris.com/risk-intelligence/search/?q={query}"
)

_TIER1_KEYWORDS = {
    "president", "prime minister", "minister", "senator",
    "parliament", "congress", "head of state", "chairman", "director general",
    "central bank", "supreme court", "chief justice", "ambassador",
}
_TIER2_KEYWORDS = {
    "deputy", "assistant minister", "mp", "member of parliament",
    "state-owned", "executive", "board member", "director", "mayor",
    "governor",
}
_TIER3_KEYWORDS = {
    "relative", "close associate", "family member", "spouse", "associate",
}


def _classify_tier(position: str) -> str:
    pos = position.lower()
    # "Deputy X" titles are tier2 even if X matches a tier1 keyword
    if "deputy" in pos:
        return "tier2"
    if any(kw in pos for kw in _TIER1_KEYWORDS):
        return "tier1"
    if any(kw in pos for kw in _TIER2_KEYWORDS):
        return "tier2"
    if any(kw in pos for kw in _TIER3_KEYWORDS):
        return "tier3"
    return "tier2"


def _parse_complyadvantage_html(html: str) -> list[dict[str, Any]]:
    """
    Parse ComplyAdvantage public search results page.
    The page renders entity cards with name, risk level, and country.
    """
    results: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # Entity cards are typically in .entity-card, .result-item, or similar
        cards = soup.select(".entity-card, .search-result, .result-row, article")
        for card in cards:
            name_el = card.select_one("h2, h3, h4, .name, .entity-name, strong")
            name = name_el.get_text(strip=True) if name_el else ""
            country_el = card.select_one(".country, .nationality, .jurisdiction")
            country = country_el.get_text(strip=True) if country_el else ""
            position_el = card.select_one(".role, .position, .title, .category")
            position = position_el.get_text(strip=True) if position_el else ""
            risk_el = card.select_one(".risk, .risk-level, .badge, .tag")
            risk = risk_el.get_text(strip=True) if risk_el else ""
            if not name:
                continue
            tier = _classify_tier(position or risk)
            results.append(
                {
                    "source": "world_check_mirror",
                    "source_site": "complyadvantage",
                    "name": name,
                    "position": position,
                    "country": country,
                    "pep_level": tier,
                    "organization": "",
                    "start_date": "",
                    "end_date": "",
                    "is_current": True,
                    "related_entities": [],
                }
            )
        # Also try table format
        if not results:
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if not rows:
                    continue
                headers = [
                    th.get_text(strip=True).lower()
                    for th in rows[0].find_all(["th", "td"])
                ]
                for row in rows[1:]:
                    cells = row.find_all("td")
                    record = {
                        headers[i] if i < len(headers) else f"col_{i}": c.get_text(strip=True)
                        for i, c in enumerate(cells)
                    }
                    name = record.get("name", "")
                    if not name:
                        continue
                    position = record.get("role", "") or record.get("position", "")
                    results.append(
                        {
                            "source": "world_check_mirror",
                            "source_site": "complyadvantage",
                            "name": name,
                            "position": position,
                            "country": record.get("country", ""),
                            "pep_level": _classify_tier(position),
                            "organization": "",
                            "start_date": "",
                            "end_date": "",
                            "is_current": True,
                            "related_entities": [],
                        }
                    )
    except Exception as exc:
        logger.debug("ComplyAdvantage HTML parse error: %s", exc)
    return results


def _parse_generic_kyc_html(html: str, source_site: str) -> list[dict[str, Any]]:
    """
    Generic HTML parser for KYC/compliance portal result pages.
    Attempts to extract name, role, and country from any table or card layout.
    """
    results: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Look for JSON-LD structured data first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "Person":
                    name = data.get("name", "")
                    if name:
                        results.append(
                            {
                                "source": "world_check_mirror",
                                "source_site": source_site,
                                "name": name,
                                "position": data.get("jobTitle", ""),
                                "country": data.get("nationality", ""),
                                "pep_level": "tier2",
                                "organization": data.get("worksFor", {}).get("name", "")
                                if isinstance(data.get("worksFor"), dict)
                                else str(data.get("worksFor", "")),
                                "start_date": "",
                                "end_date": "",
                                "is_current": True,
                                "related_entities": [],
                            }
                        )
            except Exception:
                continue

        # Fallback: scan headings and paragraphs for name/role patterns
        if not results:
            name_pattern = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+")
            for el in soup.find_all(["h1", "h2", "h3", "h4"]):
                text = el.get_text(strip=True)
                if name_pattern.match(text):
                    next_el = el.find_next_sibling()
                    position = next_el.get_text(strip=True) if next_el else ""
                    results.append(
                        {
                            "source": "world_check_mirror",
                            "source_site": source_site,
                            "name": text,
                            "position": position,
                            "country": "",
                            "pep_level": _classify_tier(position),
                            "organization": "",
                            "start_date": "",
                            "end_date": "",
                            "is_current": True,
                            "related_entities": [],
                        }
                    )
    except Exception as exc:
        logger.debug("Generic KYC HTML parse error for %s: %s", source_site, exc)
    return results


def _parse_dob_identifier(identifier: str) -> tuple[str, str]:
    """
    Split "John Smith 1975-03-14" into (name, dob_str).
    DOB must be in ISO format YYYY-MM-DD.
    """
    dob_match = re.search(r"\d{4}-\d{2}-\d{2}", identifier)
    if dob_match:
        dob = dob_match.group()
        name = identifier[: dob_match.start()].strip()
        return name, dob
    return identifier.strip(), ""


@register("world_check_mirror")
class WorldCheckMirrorCrawler(HttpxCrawler):
    """
    Searches publicly accessible KYC/AML compliance portals that surface
    World-Check style PEP and adverse media profiles.

    Uses Tor/residential proxies to avoid rate limiting on commercial
    compliance platforms.

    identifier: full name, optionally with DOB "John Smith 1975-03-14"

    Data keys returned:
        pep_matches    — list of {source, source_site, name, position, country,
                         pep_level, organization, start_date, end_date,
                         is_current, related_entities}
        is_pep         — bool
        pep_level      — str highest tier found
        match_count    — integer
        dob_used       — str DOB extracted from identifier (if any)
        query          — normalised name query
    """

    platform = "world_check_mirror"
    source_reliability = 0.85
    requires_tor = True
    proxy_tier = "residential"

    async def scrape(self, identifier: str) -> CrawlerResult:
        name, dob = _parse_dob_identifier(identifier)
        query = name
        encoded = quote_plus(query)

        all_matches: list[dict[str, Any]] = []

        ca_matches = await self._search_complyadvantage(encoded)
        all_matches.extend(ca_matches)

        dj_matches = await self._search_dowjones(encoded)
        all_matches.extend(dj_matches)

        acuris_matches = await self._search_acuris(encoded)
        all_matches.extend(acuris_matches)

        # Determine highest tier
        tiers = [m.get("pep_level", "") for m in all_matches]
        tier_rank = {"tier1": 3, "tier2": 2, "tier3": 1, "": 0}
        highest = max(tiers, key=lambda t: tier_rank.get(t, 0)) if tiers else ""

        return self._result(
            identifier,
            found=len(all_matches) > 0,
            pep_matches=all_matches,
            is_pep=len(all_matches) > 0,
            pep_level=highest,
            match_count=len(all_matches),
            dob_used=dob,
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_complyadvantage(self, encoded: str) -> list[dict[str, Any]]:
        url = _COMPLY_ADVANTAGE_URL.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code not in (200, 206):
            logger.debug(
                "ComplyAdvantage returned %s", resp.status_code if resp else "None"
            )
            return []
        return _parse_complyadvantage_html(resp.text)

    async def _search_dowjones(self, encoded: str) -> list[dict[str, Any]]:
        url = _DOW_JONES_URL.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code not in (200, 206):
            return []
        return _parse_generic_kyc_html(resp.text, "dowjones_risk")

    async def _search_acuris(self, encoded: str) -> list[dict[str, Any]]:
        url = _ACURIS_URL.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code not in (200, 206):
            return []
        return _parse_generic_kyc_html(resp.text, "acuris_risk")
