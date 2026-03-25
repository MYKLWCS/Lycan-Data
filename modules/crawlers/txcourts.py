"""
txcourts.py — Texas Courts case search crawler.

Scrapes Texas Courts (search.txcourts.gov) for case records by name.
Registered as "txcourts".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)


@register("txcourts")
class TxCourtsCrawler(HttpxCrawler):
    """
    Scrapes Texas Courts case search for a person's name.
    identifier: full name (e.g. "John Doe")
    """

    platform = "txcourts"
    SOURCE_RELIABILITY = 0.80
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        url = f"https://search.txcourts.gov/Case.aspx?cn={quote_plus(name)}"
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")

        cases = []
        # Primary: results table rows
        for row in soup.select("table.results tr, table#SearchResults tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                case_num_el = cells[0]
                party_el = cells[1] if len(cells) > 1 else None
                case_num = case_num_el.get_text(strip=True)
                if case_num and case_num.lower() != "case number":
                    cases.append({
                        "case_number": case_num,
                        "parties": party_el.get_text(strip=True) if party_el else "",
                        "case_type": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    })

        # Fallback: any element with class containing 'case-number'
        if not cases:
            for el in soup.find_all(class_=lambda c: c and "case-number" in c.lower()):
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
