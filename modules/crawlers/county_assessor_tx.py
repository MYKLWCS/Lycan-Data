"""
county_assessor_tx.py — Dallas Central Appraisal District (CAD) crawler.

Scrapes dallascad.org appraisal data by street address.
Registered as "county_assessor_tx".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# Dallas Central Appraisal District
_DCAD_URL = "https://www.dallascad.org/SearchAddr.aspx?addr={address}"


@register("county_assessor_tx")
class CountyAssessorTxCrawler(HttpxCrawler):
    """
    Scrapes Dallas CAD appraisal data by address.
    identifier: street address (e.g. "123 Main St")
    """

    platform = "county_assessor_tx"
    SOURCE_RELIABILITY = 0.85
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        url = _DCAD_URL.format(address=quote_plus(address))
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")
        parcels = []

        for row in soup.select("table.results tr, table#GridView1 tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                account_el = cells[0]
                owner_el = cells[1] if len(cells) > 1 else None
                appraised_el = cells[2] if len(cells) > 2 else None
                account = account_el.get_text(strip=True)
                # Skip header rows
                if account and account.lower() not in ("account", "account number", ""):
                    parcels.append({
                        "account": account,
                        "owner": owner_el.get_text(strip=True) if owner_el else "",
                        "appraised_value": appraised_el.get_text(strip=True) if appraised_el else "",
                    })

        if not parcels:
            # Fallback: any table row with 'account' class
            for el in soup.find_all(class_=lambda c: c and "account" in c.lower()):
                text = el.get_text(strip=True)
                if text:
                    parcels.append({"account": text, "owner": "", "appraised_value": ""})

        if not parcels:
            return self._result(identifier, found=False)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"parcels": parcels, "count": len(parcels)},
            profile_url=url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
