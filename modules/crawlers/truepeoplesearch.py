from __future__ import annotations

import logging
import random
from urllib.parse import quote

from bs4 import BeautifulSoup

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.whitepages import _parse_name_identifier

logger = logging.getLogger(__name__)


@register("truepeoplesearch")
class TruePeopleSearchCrawler(PlaywrightCrawler):
    """Scrapes TruePeopleSearch for person records by name and optional location."""

    platform = "truepeoplesearch"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.60
    requires_tor = False
    proxy_tier = "residential"

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

        # Try FlareSolverr first (bypasses Cloudflare), fall back to Playwright
        content = None
        try:
            from modules.crawlers.flaresolverr_base import FlareSolverrCrawler

            fs = FlareSolverrCrawler()
            fs.requires_tor = self.requires_tor
            fs.proxy_tier = self.proxy_tier
            if await fs._probe_flaresolverr():
                resp = await fs.fs_get(url)
                if resp and hasattr(resp, "text") and len(resp.text) > 1000:
                    if self.html_has_block_signals(resp.text):
                        logger.debug("FlareSolverr returned challenge page for %s", url)
                    else:
                        content = resp.text
        except Exception as exc:
            logger.debug("FlareSolverr unavailable for %s: %s", url, exc)

        if not content:
            async with self.page(url) as page:
                await page.wait_for_timeout(random.randint(2000, 4000))

                title = await page.title()
                if await self.is_blocked(page):
                    await self.rotate_circuit()
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=identifier,
                        found=False,
                        error=f"bot_block: challenge page for {title or url}",
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

        if not results:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_failed: no result cards extracted",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=bool(results),
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

        # Email addresses
        email_els = card.find_all(class_=lambda c: c and "email" in c.lower() if c else False)
        if not email_els:
            # Fallback: look for mailto links
            email_links = card.find_all("a", href=lambda h: h and h.startswith("mailto:"))
            data["emails"] = [a.get("href", "").replace("mailto:", "") for a in email_links]
        else:
            data["emails"] = [
                el.get_text(strip=True) for el in email_els if el.get_text(strip=True)
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
