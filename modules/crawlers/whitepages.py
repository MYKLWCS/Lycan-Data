from __future__ import annotations

import logging
import random
from urllib.parse import quote

from bs4 import BeautifulSoup

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


def _parse_name_identifier(identifier: str) -> tuple[str, str, str, str]:
    """Parse 'John Smith|Chicago,IL' → (first, last, city, state)"""
    parts = identifier.split("|")
    name_part = parts[0].strip()
    location_part = parts[1].strip() if len(parts) > 1 else ""

    name_tokens = name_part.split()
    first = name_tokens[0] if name_tokens else name_part
    last = name_tokens[-1] if len(name_tokens) > 1 else ""

    city, state = "", ""
    if "," in location_part:
        city_state = location_part.split(",")
        city = city_state[0].strip()
        state = city_state[1].strip()

    return first, last, city, state


@register("whitepages")
class WhitepagesCrawler(PlaywrightCrawler):
    """Scrapes Whitepages for people search results by name (and optional city/state)."""

    platform = "whitepages"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.65
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        first, last, city, state = _parse_name_identifier(identifier)

        # Build slug — spaces → hyphens, URL-safe
        first_slug = quote(first.replace(" ", "-"), safe="-")
        last_slug = quote(last.replace(" ", "-"), safe="-") if last else ""

        if last_slug:
            name_path = f"{first_slug}-{last_slug}"
        else:
            name_path = first_slug

        if city and state:
            city_slug = quote(city.replace(" ", "-"), safe="-")
            state_slug = quote(state.replace(" ", "-"), safe="-")
            url = f"https://www.whitepages.com/name/{name_path}/{city_slug}-{state_slug}"
        else:
            url = f"https://www.whitepages.com/name/{name_path}"

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
        if "No results" in page_text or "no results" in page_text:
            return self._result(identifier, found=False, results=[], result_count=0)

        results = []
        # Whitepages person cards use various selectors; target common card containers
        cards = soup.select(
            "div[data-testid='person-card'], li.card, div.card, article.result-card"
        )
        if not cards:
            # Fallback: any div with a class containing "card"
            cards = [
                el
                for el in soup.find_all("div")
                if el.get("class") and any("card" in c for c in el.get("class", []))
            ]

        for card in cards[:3]:
            person = _extract_whitepages_card(card)
            if person:  # pragma: no branch
                results.append(person)

        return self._result(
            identifier,
            found=True,
            results=results,
            result_count=len(results),
        )


def _extract_whitepages_card(card) -> dict | None:
    """Extract person data from a Whitepages result card."""
    try:
        data: dict = {}

        # Name
        name_el = card.find(
            ["h2", "h3", "a"], class_=lambda c: c and "name" in c.lower() if c else False
        )
        if not name_el:
            name_el = card.find(["h2", "h3"])
        data["name"] = name_el.get_text(strip=True) if name_el else ""

        # Age
        age_el = card.find(string=lambda t: t and ("Age" in t or "age" in t))
        if age_el:
            import re

            age_match = re.search(r"\d{1,3}", age_el)
            data["age"] = int(age_match.group()) if age_match else None
        else:
            data["age"] = None

        # Location
        loc_el = card.find(class_=lambda c: c and "location" in c.lower() if c else False)
        if loc_el:
            loc_text = loc_el.get_text(strip=True)
            if "," in loc_text:
                parts = loc_text.split(",", 1)
                data["city"] = parts[0].strip()
                data["state"] = parts[1].strip()
            else:
                data["city"] = loc_text
                data["state"] = ""
        else:
            data["city"] = ""
            data["state"] = ""

        # Phones
        phone_els = card.find_all(class_=lambda c: c and "phone" in c.lower() if c else False)
        data["associated_phones"] = [
            el.get_text(strip=True) for el in phone_els if el.get_text(strip=True)
        ]

        # Emails
        email_els = card.find_all(class_=lambda c: c and "email" in c.lower() if c else False)
        data["associated_emails"] = [
            el.get_text(strip=True) for el in email_els if el.get_text(strip=True)
        ]

        # Relatives
        rel_el = card.find(class_=lambda c: c and "relative" in c.lower() if c else False)
        if rel_el:
            data["relatives"] = [a.get_text(strip=True) for a in rel_el.find_all("a")]
        else:
            data["relatives"] = []

        if not data.get("name"):
            return None
        return data

    except Exception as exc:
        logger.debug("WhitePages card parse error: %s", exc)
        return None
