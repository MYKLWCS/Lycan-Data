"""
sanctions_fatf.py — FATF High-Risk Jurisdictions crawler.

Queries country-level FATF grey/black list status. The identifier is
a country name or ISO-3166-1 alpha-2/alpha-3 code.

FATF maintains two lists:
  - Black list (Call for Action): countries subject to countermeasures
  - Grey list (Increased Monitoring): countries under enhanced scrutiny

Sources:
  - Static embedded list (always available, updated with each deployment)
  - Live FATF website scrape (attempted first, falls back to embedded list)

Registered as "sanctions_fatf".
"""

from __future__ import annotations

import logging
import re

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_FATF_URL = "https://www.fatf-gafi.org/en/topics/high-risk-and-other-monitored-jurisdictions.html"

# Embedded known lists as of 2024 — used as fallback when live scrape fails.
# Source: FATF plenary October 2024 outcomes.
_EMBEDDED_BLACK_LIST: frozenset[str] = frozenset(
    {
        "North Korea",
        "Iran",
        "Myanmar",
    }
)

_EMBEDDED_GREY_LIST: frozenset[str] = frozenset(
    {
        "Algeria",
        "Angola",
        "Bulgaria",
        "Burkina Faso",
        "Cameroon",
        "Côte d'Ivoire",
        "Cote d'Ivoire",
        "Croatia",
        "Democratic Republic of Congo",
        "DRC",
        "Haiti",
        "Kenya",
        "Laos",
        "Lebanon",
        "Mali",
        "Monaco",
        "Mozambique",
        "Namibia",
        "Nigeria",
        "Philippines",
        "Senegal",
        "South Africa",
        "South Sudan",
        "Syria",
        "Tanzania",
        "Venezuela",
        "Vietnam",
        "Yemen",
    }
)

# ISO-2/ISO-3 → country name aliases for quick lookups
_ISO_ALIASES: dict[str, str] = {
    "KP": "North Korea",
    "PRK": "North Korea",
    "IR": "Iran",
    "IRN": "Iran",
    "MM": "Myanmar",
    "MMR": "Myanmar",
    "DZ": "Algeria",
    "BF": "Burkina Faso",
    "CM": "Cameroon",
    "CI": "Côte d'Ivoire",
    "HR": "Croatia",
    "CD": "Democratic Republic of Congo",
    "HT": "Haiti",
    "KE": "Kenya",
    "LA": "Laos",
    "LB": "Lebanon",
    "ML": "Mali",
    "MC": "Monaco",
    "MZ": "Mozambique",
    "NA": "Namibia",
    "NG": "Nigeria",
    "PH": "Philippines",
    "SN": "Senegal",
    "ZA": "South Africa",
    "SS": "South Sudan",
    "SY": "Syria",
    "TZ": "Tanzania",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "YE": "Yemen",
    "AO": "Angola",
}


def _resolve_country(identifier: str) -> str:
    """Resolve ISO code or country name to canonical name."""
    upper = identifier.strip().upper()
    if upper in _ISO_ALIASES:
        return _ISO_ALIASES[upper]
    return identifier.strip()


def _match_country(query: str, country_set: frozenset[str]) -> bool:
    """Case-insensitive substring match of query against a country set."""
    q_lower = query.lower()
    return any(q_lower in c.lower() or c.lower() in q_lower for c in country_set)


def _parse_fatf_page(html: str) -> tuple[list[str], list[str]]:
    """
    Parse FATF HTML page to extract black/grey list countries.
    Returns (black_list, grey_list) as lists of country names.
    Falls back to empty lists if parsing fails — caller uses embedded lists.
    """
    try:
        # FATF page typically contains sections with "Call for Action" and
        # "Increased Monitoring" headings followed by country names.
        # Extract text blocks between section markers.
        black: list[str] = []
        grey: list[str] = []

        # Strip tags for text extraction
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"\s+", " ", text)

        # Look for "Jurisdictions under increased monitoring" section
        grey_match = re.search(
            r"Jurisdictions under increased monitoring(.*?)(?:Call for Action|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if grey_match:
            # Extract capitalized country-like names (2+ words starting uppercase)
            country_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\b")
            grey_candidates = country_pattern.findall(grey_match.group(1))
            # Filter out common non-country words
            skip = {
                "The",
                "And",
                "Of",
                "In",
                "For",
                "With",
                "This",
                "That",
                "These",
                "FATF",
                "Plenary",
                "October",
                "June",
                "February",
                "March",
                "April",
                "May",
                "July",
                "August",
                "September",
                "November",
                "December",
                "January",
                "Member",
                "States",
            }
            grey = [c for c in grey_candidates if c not in skip and len(c) > 3]

        # Look for "Call for Action" section
        black_match = re.search(
            r"Call for Action(.*?)(?:Jurisdictions under|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if black_match:
            country_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\b")
            black_candidates = country_pattern.findall(black_match.group(1))
            skip = {
                "The",
                "And",
                "Of",
                "In",
                "For",
                "With",
                "FATF",
                "Plenary",
                "Member",
                "States",
            }
            black = [c for c in black_candidates if c not in skip and len(c) > 3]

        return black, grey
    except Exception as exc:
        logger.debug("FATF HTML parse failed: %s", exc)
        return [], []


@register("sanctions_fatf")
class FATFCrawler(HttpxCrawler):
    """
    Checks whether a country is on the FATF grey list (Increased Monitoring)
    or black list (Call for Action).

    identifier: country name or ISO-3166-1 alpha-2/alpha-3 code
                (e.g. "Iran", "IR", "IRN", "North Korea", "KP")

    Data keys returned:
        country         — resolved country name
        status          — "black_list" | "grey_list" | "clean" | "unknown"
        black_list      — True if on Call for Action list
        grey_list       — True if on Increased Monitoring list
        source          — "live" | "embedded"
        black_list_countries — current known black list countries
        grey_list_countries  — current known grey list countries
    """

    platform = "sanctions_fatf"
    category = CrawlerCategory.SANCTIONS_AML
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        country = _resolve_country(identifier)

        # Attempt live FATF page scrape
        black_list = list(_EMBEDDED_BLACK_LIST)
        grey_list = list(_EMBEDDED_GREY_LIST)
        source = "embedded"

        resp = await self.get(_FATF_URL)
        if resp is not None and resp.status_code == 200:
            live_black, live_grey = _parse_fatf_page(resp.text)
            if live_black or live_grey:
                black_list = live_black or black_list
                grey_list = live_grey or grey_list
                source = "live"
                logger.debug(
                    "FATF: live parse — black=%d grey=%d",
                    len(black_list),
                    len(grey_list),
                )
        else:
            logger.debug("FATF: using embedded list (live fetch unavailable)")

        frozenset(b.lower() for b in black_list)
        frozenset(g.lower() for g in grey_list)

        on_black = _match_country(country, frozenset(black_list))
        on_grey = _match_country(country, frozenset(grey_list))

        if on_black:
            status = "black_list"
        elif on_grey:
            status = "grey_list"
        else:
            status = "clean"

        return self._result(
            identifier,
            found=on_black or on_grey,
            country=country,
            status=status,
            black_list=on_black,
            grey_list=on_grey,
            source=source,
            black_list_countries=sorted(black_list),
            grey_list_countries=sorted(grey_list),
        )
