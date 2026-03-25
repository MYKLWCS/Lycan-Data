"""
people_thatsthem.py — ThatsThem people-search scraper.

Supports three lookup modes determined by the identifier format:
  - Phone   : starts with digits or "+" → /phone/{phone}
  - Email   : contains "@"              → /email/{email}
  - Name    : everything else           → /name/{first}-{last}

Returns a list of person cards parsed from the HTML response.
Registered as "people_thatsthem".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.flaresolverr_base import FlareSolverrCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://thatsthem.com"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://thatsthem.com/",
}


# ---------------------------------------------------------------------------
# Identifier routing
# ---------------------------------------------------------------------------


def _build_url(identifier: str) -> tuple[str, str]:
    """Return (url, mode) for the given identifier."""
    s = identifier.strip()
    if s.startswith("+") or re.match(r"^\d", s):
        phone = re.sub(r"[^\d+]", "", s)
        return f"{_BASE}/phone/{phone}", "phone"
    if "@" in s:
        return f"{_BASE}/email/{quote_plus(s)}", "email"
    parts = s.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    slug = f"{first}-{last}".strip("-")
    return f"{_BASE}/name/{slug}", "name"


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------


def _text(tag: Any) -> str:
    """Return stripped inner text of a BeautifulSoup tag, or ''."""
    return tag.get_text(separator=" ", strip=True) if tag else ""


def _parse_persons(html: str) -> list[dict[str, Any]]:
    """Parse ThatsThem result cards from HTML."""
    persons: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Each person record is contained in a <div class="ThatsThem-record ...">
        # or similar wrapper. We look for the common data-item attribute pattern.
        cards = soup.select("div.record, div[class*='record'], li[class*='record']")

        # Fallback: look for any block that contains a name heading
        if not cards:
            cards = soup.select("div.people-record, div.result-item, article")

        for card in cards:
            person: dict[str, Any] = {}

            # Name
            name_tag = card.select_one("h2, h3, .name, [class*='name']")
            if name_tag:
                person["name"] = _text(name_tag)

            # Address lines
            addr_tag = card.select_one(".address, [class*='address'], [itemprop='address']")
            if addr_tag:
                person["address"] = _text(addr_tag)

            # Phone numbers
            phones: list[str] = []
            for ph in card.select("a[href^='tel:'], .phone, [class*='phone']"):
                ph_text = _text(ph).strip()
                if ph_text:
                    phones.append(ph_text)
            if phones:
                person["phones"] = list(dict.fromkeys(phones))

            # Emails
            emails: list[str] = []
            for em in card.select("a[href^='mailto:'], .email, [class*='email']"):
                em_text = _text(em).strip()
                if not em_text:
                    href = em.get("href", "")
                    em_text = href.replace("mailto:", "").strip()
                if em_text:
                    emails.append(em_text)
            if emails:
                person["emails"] = list(dict.fromkeys(emails))

            # Age
            age_tag = card.select_one(".age, [class*='age']")
            if age_tag:
                m = re.search(r"\d{1,3}", _text(age_tag))
                if m:  # pragma: no branch
                    person["age"] = int(m.group())

            if person.get("name") or person.get("address"):
                persons.append(person)
    except Exception as exc:
        logger.warning("ThatsThem HTML parse error: %s", exc)

    return persons


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("people_thatsthem")
class PeopleThatsThemCrawler(FlareSolverrCrawler):
    """
    Scrapes ThatsThem for people-search data.

    identifier: phone number, email address, or full name.
    Lookup mode is inferred automatically from the identifier format.

    source_reliability: 0.75 — aggregated public records, accuracy varies.
    """

    platform = "people_thatsthem"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.75
    requires_tor = True
    tor_instance = TorInstance.TOR1

    async def scrape(self, identifier: str) -> CrawlerResult:
        url, mode = _build_url(identifier)

        response = await self.get(url, headers=_HEADERS)

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

        if response.status_code == 404:
            return self._result(identifier, found=False, persons=[], query=identifier, mode=mode)

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        persons = _parse_persons(response.text)
        found = len(persons) > 0

        return self._result(
            identifier,
            found=found,
            persons=persons,
            query=identifier,
            mode=mode,
            profile_url=url,
        )
