"""
freepeoplesearch.py — FreePeopleSearch crawler.

Searches https://www.freepeoplesearch.com/name/{first}-{last} for public records
containing name, age, phone numbers, addresses, and relatives.

Registered as "freepeoplesearch".
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")


def _validate_phone(raw: str) -> str | None:
    """Validate and format a US phone number. Returns E164 or None."""
    try:
        import phonenumbers

        parsed = phonenumbers.parse(raw, "US")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        logger.debug("Failed to normalize phone number %r", raw, exc_info=True)
    return None


@register("freepeoplesearch")
class FreePeopleSearchCrawler(CurlCrawler):
    """Scrapes FreePeopleSearch for public records by name."""

    platform = "freepeoplesearch"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=3.0)
    source_reliability = 0.50
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        # Parse "First Last|City,State" format
        name = identifier.split("|")[0].strip()
        if not name:
            return self._result(identifier, found=False)

        slug = name.lower().replace(" ", "-")
        url = f"https://www.freepeoplesearch.com/name/{slug}"

        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        persons = _parse_results(resp.text)
        has_data = len(persons) > 0

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=has_data,
            data={
                "persons": persons[:10],
                "result_count": len(persons),
                "profile_url": url,
            },
            source_reliability=self.source_reliability,
        )


def _parse_results(html: str) -> list[dict]:
    """Parse person cards from FreePeopleSearch HTML."""
    persons = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        cards = soup.select(
            "div.card, div.person-card, div[class*='result'], "
            "div[class*='person'], article, li[class*='result']"
        )

        for card in cards[:10]:
            person = {}

            # Name
            name_el = card.find(["h2", "h3", "h4", "strong"])
            if name_el:
                person["name"] = name_el.get_text(strip=True)

            card_text = card.get_text(" ", strip=True)

            # Age
            age_match = re.search(r"[Aa]ge\s+(\d{1,3})", card_text)
            if age_match:
                person["age"] = int(age_match.group(1))

            # Address
            addr_el = card.find(class_=lambda c: c and "address" in c.lower() if c else False)
            if addr_el:
                person["address"] = addr_el.get_text(strip=True)

            # Phone numbers — validate with phonenumbers library
            raw_phones = _PHONE_RE.findall(card_text)
            validated = []
            for raw in raw_phones:
                formatted = _validate_phone(raw)
                if formatted:
                    validated.append(formatted)
            if validated:
                person["phones"] = list(dict.fromkeys(validated))

            # Relatives
            rel_el = card.find(class_=lambda c: c and "relative" in c.lower() if c else False)
            if rel_el:
                person["relatives"] = [a.get_text(strip=True) for a in rel_el.find_all("a")]

            if person.get("name"):
                persons.append(person)
    except Exception as exc:
        logger.debug("FreePeopleSearch parse error: %s", exc)
    return persons
