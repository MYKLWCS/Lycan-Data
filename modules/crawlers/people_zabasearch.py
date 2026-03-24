"""
people_zabasearch.py — ZabaSearch people-search scraper.

Queries https://www.zabasearch.com/people/{first}+{last}/ for public records
containing name, city, state, age, and phone.

Registered as "people_zabasearch".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.zabasearch.com/people/{first}+{last}/"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.zabasearch.com/",
}


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------


def _text(tag: Any) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def _parse_persons(html: str) -> list[dict[str, Any]]:
    """Parse ZabaSearch result rows from HTML."""
    persons: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # ZabaSearch wraps each record in a <div class="person-search-result"> or similar
        cards = soup.select(
            "div.person-search-result, div[class*='person'], li[class*='person'], "
            "div.result-block, div[id*='result']"
        )

        # Generic fallback: any h2/h3 that looks like a name followed by location data
        if not cards:
            cards = soup.select("div.search-result, article, section[class*='result']")

        for card in cards:
            person: dict[str, Any] = {}

            # Name
            name_tag = card.select_one("h2, h3, .name, [class*='fullname'], [class*='name']")
            if name_tag:
                person["name"] = _text(name_tag)

            # City and state often appear as "City, ST"
            loc_tag = card.select_one(
                ".location, [class*='city'], [class*='location'], [class*='address']"
            )
            if loc_tag:
                loc_text = _text(loc_tag)
                m = re.match(r"^([^,]+),\s*([A-Z]{2})", loc_text)
                if m:
                    person["city"] = m.group(1).strip()
                    person["state"] = m.group(2).strip()
                else:
                    person["location"] = loc_text

            # Age
            age_tag = card.select_one(".age, [class*='age']")
            if age_tag:
                m = re.search(r"\d{1,3}", _text(age_tag))
                if m:
                    person["age"] = int(m.group())
            else:
                # Try inline "Age 55" patterns in the card text
                card_text = card.get_text()
                m = re.search(r"\bage\s*[:\-]?\s*(\d{1,3})\b", card_text, re.IGNORECASE)
                if m:
                    person["age"] = int(m.group(1))

            # Phone
            phones: list[str] = []
            for ph in card.select("a[href^='tel:'], .phone, [class*='phone']"):
                ph_text = _text(ph).strip()
                if not ph_text:
                    href = ph.get("href", "")
                    ph_text = href.replace("tel:", "").strip()
                if ph_text:
                    phones.append(ph_text)
            # Regex fallback for phone patterns in card text
            if not phones:
                raw_phones = re.findall(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", card.get_text())
                phones = list(dict.fromkeys(raw_phones))
            if phones:
                person["phones"] = phones

            if person.get("name") or person.get("city"):
                persons.append(person)
    except Exception as exc:
        logger.warning("ZabaSearch HTML parse error: %s", exc)

    return persons


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("people_zabasearch")
class PeopleZabaSearchCrawler(HttpxCrawler):
    """
    Scrapes ZabaSearch for public people records.

    identifier: full name — "First Last" (single space separated).
    Names with more tokens: first token is first name, remainder is last name.

    source_reliability: 0.70 — public records aggregator, variable completeness.
    """

    platform = "people_zabasearch"
    source_reliability = 0.70
    requires_tor = True
    tor_instance = TorInstance.TOR1

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        parts = name.split(" ", 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""

        url = _BASE_URL.format(first=first, last=last)

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
            return self._result(identifier, found=False, persons=[], query=name)

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
            query=name,
            profile_url=url,
        )
