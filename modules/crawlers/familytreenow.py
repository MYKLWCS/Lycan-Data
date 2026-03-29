"""
familytreenow.py — FamilyTreeNow genealogy public records crawler.

Scrapes familytreenow.com public records search for person cards.
Registered as "familytreenow".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("familytreenow")
class FamilyTreeNowCrawler(HttpxCrawler):
    """
    Scrapes FamilyTreeNow genealogy search for person cards.
    identifier: full name (e.g. "John Doe") or "FirstName LastName"
    """

    platform = "familytreenow"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    SOURCE_RELIABILITY = 0.55
    source_reliability = SOURCE_RELIABILITY
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split()
        first = quote_plus(parts[0]) if parts else ""
        last = quote_plus(parts[-1]) if len(parts) > 1 else ""
        url = f"https://www.familytreenow.com/search/genealogy/results?fn={first}&ln={last}"

        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all(class_="card-block")
        if not cards:
            if soup.find(string=lambda t: t and "no results" in t.lower()):
                return self._result(identifier, found=False)
            return self._result(identifier, found=False)

        persons = []
        for card in cards[:10]:
            name_el = card.find(class_="name") or card.find("h4") or card.find("h3")
            age_el = card.find(class_="age")
            loc_el = card.find(class_="location") or card.find(class_="address")
            persons.append(
                {
                    "name": name_el.get_text(strip=True) if name_el else "",
                    "age": age_el.get_text(strip=True) if age_el else "",
                    "location": loc_el.get_text(strip=True) if loc_el else "",
                }
            )

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"persons": persons, "result_count": len(persons)},
            profile_url=url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
