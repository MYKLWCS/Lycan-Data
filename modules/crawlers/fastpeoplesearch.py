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


@register("fastpeoplesearch")
class FastPeopleSearchCrawler(PlaywrightCrawler):
    """Scrapes FastPeopleSearch for person records by name."""

    platform = "fastpeoplesearch"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.60
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        first, last, city, state = _parse_name_identifier(identifier)

        first_slug = quote(first.replace(" ", "-"), safe="-")
        last_slug = quote(last.replace(" ", "-"), safe="-") if last else ""

        if last_slug:
            name_path = f"{first_slug}-{last_slug}"
        else:
            name_path = first_slug

        if city and state:
            city_slug = quote(city.replace(" ", "-"), safe="-")
            state_slug = quote(state.replace(" ", "-"), safe="-")
            url = f"https://www.fastpeoplesearch.com/name/{name_path}_{city_slug}-{state_slug}"
        else:
            url = f"https://www.fastpeoplesearch.com/name/{name_path}"

        # Try FlareSolverr first (bypasses Cloudflare), fall back to Playwright
        content = None
        try:
            from modules.crawlers.flaresolverr_base import FlareSolverrCrawler
            fs = FlareSolverrCrawler()
            if await fs._probe_flaresolverr():
                resp = await fs.fs_get(url)
                if resp and hasattr(resp, 'text') and len(resp.text) > 1000:
                    content = resp.text
                    logger.debug("FlareSolverr returned %d bytes for %s", len(content), url)
        except Exception as exc:
            logger.debug("FlareSolverr unavailable for %s: %s", url, exc)

        if not content:
            async with self.page(url) as page:
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
            return self._result(identifier, found=True, results=[], result_count=0)

        results = []
        cards = soup.select("div.card-block")

        for card in cards[:5]:
            person = _extract_fps_card(card)
            if person:  # pragma: no branch
                results.append(person)

        return self._result(
            identifier,
            found=True,
            results=results,
            result_count=len(results),
        )


def _extract_fps_card(card) -> dict | None:
    """Extract person data from a FastPeopleSearch card-block."""
    try:
        import re

        data: dict = {}

        # Full name — typically in an <h2> or <strong>
        name_el = card.find(["h2", "h3", "strong"])
        data["full_name"] = name_el.get_text(strip=True) if name_el else ""

        # Age — look for text pattern like "Age 45"
        card_text = card.get_text(" ", strip=True)
        age_match = re.search(r"[Aa]ge\s+(\d{1,3})", card_text)
        data["age"] = int(age_match.group(1)) if age_match else None

        # City/state — look for location element
        loc_el = card.find(
            class_=lambda c: c and ("location" in c.lower() or "city" in c.lower()) if c else False
        )
        data["city_state"] = loc_el.get_text(strip=True) if loc_el else ""

        # Phone numbers
        phone_els = card.find_all(class_=lambda c: c and "phone" in c.lower() if c else False)
        if not phone_els:
            # Fallback: find tel: links
            phone_links = card.find_all("a", href=lambda h: h and h.startswith("tel:"))
            data["phone_numbers"] = [a.get_text(strip=True) for a in phone_links]
        else:
            data["phone_numbers"] = [
                el.get_text(strip=True) for el in phone_els if el.get_text(strip=True)
            ]

        # Addresses
        addr_els = card.find_all(class_=lambda c: c and "address" in c.lower() if c else False)
        data["addresses"] = [el.get_text(strip=True) for el in addr_els if el.get_text(strip=True)]

        if not data.get("full_name"):
            return None
        return data

    except Exception as exc:
        logger.debug("FastPeopleSearch card parse error: %s", exc)
        return None
