"""
ca_courts.py — California LA Superior Court case search crawler.

Scrapes lacourt.org case summary search for case records.
Registered as "ca_courts".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

# LA Superior Court case summary search
_SEARCH_URL = "https://www.lacourt.org/casesummary/ui/"


@register("ca_courts")
class CaCourtsCrawler(HttpxCrawler):
    """
    Scrapes LA Superior Court case search (lacourt.org).
    identifier: full name (e.g. "John Doe")
    """

    platform = "ca_courts"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    SOURCE_RELIABILITY = 0.80
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        url = f"{_SEARCH_URL}?q={quote_plus(name)}"
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")

        cases = []
        # Primary: table with id 'caselist' or class 'case-table'
        for row in soup.select("table#caselist tr, table.case-table tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                case_num = cells[0].get_text(strip=True)
                parties = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                case_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                if case_num and case_num.lower() not in ("case number", "case #", ""):
                    cases.append(
                        {
                            "case_number": case_num,
                            "parties": parties,
                            "case_type": case_type,
                        }
                    )

        if not cases:
            # Generic fallback: any element with class containing 'case-row'
            for el in soup.find_all(
                attrs={
                    "class": lambda c: (
                        c
                        and "case-row" in (c.lower() if isinstance(c, str) else " ".join(c).lower())
                    )
                }
            ):
                text = el.get_text(strip=True)
                if text:
                    cases.append({"case_number": text, "parties": "", "case_type": ""})

        if not cases:
            return self._result(identifier, found=False)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"cases": cases, "count": len(cases)},
            profile_url=url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
