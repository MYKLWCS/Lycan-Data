from __future__ import annotations

import logging
import random
from urllib.parse import quote

from bs4 import BeautifulSoup

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.whitepages import _parse_name_identifier
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("truepeoplesearch")
class TruePeopleSearchCrawler(PlaywrightCrawler):
    """Scrapes TruePeopleSearch for person records by name and optional location."""

    platform = "truepeoplesearch"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.60
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        first, last, city, state = _parse_name_identifier(identifier)

        name_query = f"{first} {last}".strip()
        encoded_name = quote(name_query)

        location_query = ""
        if city and state:
            location_query = f"{city},{state}"

        encoded_location = quote(location_query, safe="%,")
        url = (
            f"https://www.truepeoplesearch.com/results"
            f"?name={encoded_name}&citystatezip={encoded_location}"
        )

        async with self.page(url) as page:
            # Human-like delay before scraping
            await page.wait_for_timeout(random.randint(2000, 4000))

            title = await page.title()
            if any(s in title.lower() for s in ("access denied", "blocked", "403")):
                await self.rotate_circuit()
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="bot_block: page title indicates block",
                    source_reliability=self.source_reliability,
                )

            content = await page.content()

        soup = BeautifulSoup(content, "html.parser")

        # No-results sentinel
        page_text = soup.get_text(" ", strip=True)
        if "No Records Found" in page_text:
            return self._result(identifier, found=False, results=[], result_count=0)

        results = []
        cards = soup.select("div.card")

        for card in cards[:5]:
            person = _extract_tps_card(card)
            if person:  # pragma: no branch
                results.append(person)

        return self._result(
            identifier,
            found=True,
            results=results,
            result_count=len(results),
        )


def _extract_tps_card(card) -> dict | None:
    """Extract person data from a TruePeopleSearch .card element."""
    try:
        import re

        data: dict = {}

        # Full name
        name_el = card.find(
            ["h2", "h3", "div"], class_=lambda c: c and "name" in c.lower() if c else False
        )
        if not name_el:
            name_el = card.find(["h2", "h3"])
        data["full_name"] = name_el.get_text(strip=True) if name_el else ""

        card_text = card.get_text(" ", strip=True)

        # Age
        age_match = re.search(r"[Aa]ge\s+(\d{1,3})", card_text)
        data["age"] = int(age_match.group(1)) if age_match else None

        # Address
        addr_el = card.find(class_=lambda c: c and "address" in c.lower() if c else False)
        data["address"] = addr_el.get_text(strip=True) if addr_el else ""

        # Phone numbers
        phone_els = card.find_all(class_=lambda c: c and "phone" in c.lower() if c else False)
        if not phone_els:
            phone_links = card.find_all("a", href=lambda h: h and h.startswith("tel:"))
            data["phone_numbers"] = [a.get_text(strip=True) for a in phone_links]
        else:
            data["phone_numbers"] = [
                el.get_text(strip=True) for el in phone_els if el.get_text(strip=True)
            ]

        # Relatives
        rel_el = card.find(class_=lambda c: c and "relative" in c.lower() if c else False)
        if rel_el:
            data["relatives"] = [a.get_text(strip=True) for a in rel_el.find_all("a")]
        else:
            data["relatives"] = []

        # Associates
        assoc_el = card.find(class_=lambda c: c and "associate" in c.lower() if c else False)
        if assoc_el:
            data["associates"] = [a.get_text(strip=True) for a in assoc_el.find_all("a")]
        else:
            data["associates"] = []

        if not data.get("full_name"):
            return None
        return data

    except Exception as exc:
        logger.debug("TruePeopleSearch card parse error: %s", exc)
        return None
