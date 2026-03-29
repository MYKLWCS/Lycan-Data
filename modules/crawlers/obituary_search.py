"""
Obituary search crawler — scrapes Legacy.com and FindAGrave for mentions of a
name or their family members. Survived-by / preceded-by parsing surfaces living
vs deceased relatives without any active probing of the subject.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("obituary_search")
class ObituarySearchCrawler(HttpxCrawler):
    """
    Searches Legacy.com and FindAGrave for obituaries matching a name.

    identifier format: "Firstname Lastname" or "Firstname Lastname|City,State"
    """

    platform = "obituary_search"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.80  # obituaries are authoritative for death data
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.split("|")
        name = parts[0].strip()
        location = parts[1].strip() if len(parts) > 1 else ""

        obituaries: list[dict] = []

        # --- Legacy.com ---
        legacy_results = await self._scrape_legacy(name, location)
        obituaries.extend(legacy_results)

        # --- FindAGrave ---
        findagrave_results = await self._scrape_findagrave(name)
        obituaries.extend(findagrave_results)

        found = len(obituaries) > 0

        return self._result(
            identifier=identifier,
            found=found,
            obituaries=obituaries,
            query=name,
            sources_checked=["legacy.com", "findagrave.com"],
        )

    # ── Legacy.com ────────────────────────────────────────────────────────────

    async def _scrape_legacy(self, name: str, location: str) -> list[dict]:
        encoded = quote(name)
        url = f"https://www.legacy.com/obituaries/search?keyword={encoded}"
        if location:
            url += f"&location={quote(location)}"

        response = await self.get(url)
        if not response or response.status_code != 200:
            logger.warning("legacy.com request failed for query: %s", name)
            return []

        return _parse_legacy(response.text, name)

    # ── FindAGrave ────────────────────────────────────────────────────────────

    async def _scrape_findagrave(self, name: str) -> list[dict]:
        encoded = quote(name)
        url = f"https://www.findagrave.com/memorial/search?query={encoded}"

        response = await self.get(url)
        if not response or response.status_code != 200:
            logger.warning("findagrave.com request failed for query: %s", name)
            return []

        return _parse_findagrave(response.text, name)


# ── Parsers ───────────────────────────────────────────────────────────────────


def _parse_legacy(html: str, query: str) -> list[dict]:
    """Parse Legacy.com search results page."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Legacy.com listing containers
    listings = soup.select(
        "div.obituary-listing, div[data-component='ObituaryCard'], article.obit-card"
    )
    if not listings:
        # Fallback: any section that looks like an obit listing
        listings = [
            el
            for el in soup.find_all("div")
            if el.get("class")
            and any("obituary" in c.lower() or "obit" in c.lower() for c in el.get("class", []))
        ]

    for card in listings[:10]:
        obit = _extract_legacy_card(card)
        if obit:
            obit["source"] = "legacy.com"
            results.append(obit)

    return results


def _extract_legacy_card(card) -> dict | None:
    """Extract structured obituary data from a Legacy.com result card."""
    try:
        data: dict = {}

        # Name
        name_el = card.find(
            ["h3", "h2", "a"], class_=lambda c: c and "name" in c.lower() if c else False
        )
        if not name_el:
            name_el = card.find(["h3", "h2"])
        data["name"] = name_el.get_text(strip=True) if name_el else ""

        # Age
        age_el = card.find(string=lambda t: t and re.search(r"\bage\s+\d{1,3}\b", t or "", re.I))
        if age_el:
            age_m = re.search(r"\b(\d{1,3})\b", age_el)
            data["age"] = int(age_m.group(1)) if age_m else None
        else:
            data["age"] = None

        # Date
        date_el = card.find(class_=lambda c: c and "date" in c.lower() if c else False)
        data["date"] = date_el.get_text(strip=True) if date_el else None

        # Location
        loc_el = card.find(
            class_=lambda c: c and ("location" in c.lower() or "city" in c.lower()) if c else False
        )
        data["location"] = loc_el.get_text(strip=True) if loc_el else None

        # Full text for survived_by / preceded_by
        full_text = card.get_text(" ", strip=True)
        data["survived_by"] = _extract_survived_by(full_text)
        data["preceded_by"] = _extract_preceded_by(full_text)

        if not data.get("name"):
            return None
        return data

    except Exception as exc:
        logger.debug("Legacy.com card parse error: %s", exc)
        return None


def _parse_findagrave(html: str, query: str) -> list[dict]:
    """Parse FindAGrave search results page."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # FindAGrave memorial cards
    memorials = soup.select("div.memorial-item, li.memorial, div[data-memorial-id]")
    if not memorials:
        memorials = soup.select("div.search-result, li.search-result-item")

    for card in memorials[:10]:
        obit = _extract_findagrave_card(card)
        if obit:
            obit["source"] = "findagrave.com"
            results.append(obit)

    return results


def _extract_findagrave_card(card) -> dict | None:
    """Extract structured data from a FindAGrave memorial card."""
    try:
        data: dict = {}

        name_el = card.find(
            ["a", "h3", "h2"], class_=lambda c: c and "name" in c.lower() if c else False
        )
        if not name_el:
            name_el = card.find(["h3", "h2", "a"])
        data["name"] = name_el.get_text(strip=True) if name_el else ""

        full_text = card.get_text(" ", strip=True)

        # Birth/death years
        year_m = re.findall(r"\b(18|19|20)\d{2}\b", full_text)
        data["birth_year"] = year_m[0] if len(year_m) > 0 else None
        data["death_year"] = year_m[1] if len(year_m) > 1 else None
        data["date"] = f"{data['birth_year']}–{data['death_year']}" if data["birth_year"] else None
        data["age"] = None
        data["location"] = None
        data["survived_by"] = _extract_survived_by(full_text)
        data["preceded_by"] = _extract_preceded_by(full_text)

        if not data.get("name"):
            return None
        return data

    except Exception as exc:
        logger.debug("FindAGrave card parse error: %s", exc)
        return None


# ── Text extraction helpers ───────────────────────────────────────────────────


def _extract_survived_by(text: str) -> list[str]:
    """
    Pull names listed after 'survived by' — these are still-living relatives.
    Returns a list of name strings (best-effort).
    """
    text_lower = text.lower()
    markers = ["survived by", "is survived by", "are survived by", "left to cherish"]
    for marker in markers:
        idx = text_lower.find(marker)
        if idx != -1:
            segment = text[idx + len(marker) : idx + len(marker) + 400]
            # Stop at next structural marker
            stop = re.search(
                r"(?:preceded by|in lieu|memorial service|funeral|visitation|\.)", segment, re.I
            )
            if stop:
                segment = segment[: stop.start()]
            names = _extract_names_from_segment(segment)
            return names
    return []


def _extract_preceded_by(text: str) -> list[str]:
    """
    Pull names listed after 'preceded in death by' — these are deceased relatives.
    Returns a list of name strings (best-effort).
    """
    text_lower = text.lower()
    markers = ["preceded in death by", "preceded by", "predeceased by"]
    for marker in markers:
        idx = text_lower.find(marker)
        if idx != -1:
            segment = text[idx + len(marker) : idx + len(marker) + 400]
            stop = re.search(
                r"(?:survived by|memorial service|funeral|visitation|\.)", segment, re.I
            )
            if stop:
                segment = segment[: stop.start()]
            names = _extract_names_from_segment(segment)
            return names
    return []


def _extract_names_from_segment(segment: str) -> list[str]:
    """
    Heuristically extract proper names from a comma/semicolon separated segment.
    Returns up to 10 names.
    """
    # Split on , and ; and "and"
    tokens = re.split(r"[,;]|\band\b", segment)
    names = []
    for token in tokens:
        token = token.strip()
        # A likely name: 2-4 capitalised words, no digits, reasonable length
        if re.match(r"^[A-Z][a-zA-Z\-']{1,20}(\s[A-Z][a-zA-Z\-']{1,20}){0,3}$", token):
            names.append(token)
        if len(names) >= 10:  # pragma: no branch
            break
    return names
