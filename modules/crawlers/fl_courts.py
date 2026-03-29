"""
fl_courts.py — Orange County Florida Clerk of Courts case search crawler.

Scrapes myeclerk.myorangeclerk.com for case records.
Registered as "fl_courts".
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


@register("fl_courts")
class FlCourtsCrawler(HttpxCrawler):
    """
    Scrapes Orange County Florida Clerk of Courts case search.
    identifier: full name (e.g. "John Doe")
    """

    platform = "fl_courts"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    SOURCE_RELIABILITY = 0.80
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        url = f"https://myeclerk.myorangeclerk.com/Cases/Search?name={quote_plus(name)}"
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")

        cases = []
        for item in soup.find_all(class_="case-result")[:20]:
            case_num_el = item.find(class_="case-number") or item.find(class_="caseNumber")
            party_el = item.find(class_="party") or item.find(class_="partyName")
            status_el = item.find(class_="status") or item.find(class_="caseStatus")
            case_num = case_num_el.get_text(strip=True) if case_num_el else ""
            if case_num:
                cases.append(
                    {
                        "case_number": case_num,
                        "party": party_el.get_text(strip=True) if party_el else "",
                        "status": status_el.get_text(strip=True) if status_el else "",
                    }
                )

        if not cases:
            # Generic table row fallback
            for row in soup.select("table tbody tr"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    case_num = cells[0].get_text(strip=True)
                    if case_num and not case_num.lower().startswith("case"):
                        cases.append(
                            {
                                "case_number": case_num,
                                "party": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                                "status": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                            }
                        )

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
