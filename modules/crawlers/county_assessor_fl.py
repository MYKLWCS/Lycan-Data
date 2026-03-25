"""
county_assessor_fl.py — Orange County FL Property Appraiser crawler.

Scrapes ocpafl.org for parcel data by address.
Registered as "county_assessor_fl".
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

# Orange County FL Property Appraiser
_OCPA_URL = "https://www.ocpafl.org/searches/ParcelSearch.aspx?addr={address}"


@register("county_assessor_fl")
class CountyAssessorFlCrawler(HttpxCrawler):
    """
    Scrapes Orange County FL Property Appraiser for parcel data.
    identifier: street address (e.g. "123 Main St Orlando FL")
    """

    platform = "county_assessor_fl"
    category = CrawlerCategory.PROPERTY
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    SOURCE_RELIABILITY = 0.85
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        url = _OCPA_URL.format(address=quote_plus(address))
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(resp.text, "html.parser")
        parcels = []

        for item in soup.find_all(class_="parcel-result")[:10]:
            parcel_id_el = item.find(class_="parcel-id") or item.find(class_="parcelId")
            owner_el = item.find(class_="owner-name") or item.find(class_="ownerName")
            value_el = item.find(class_="just-value") or item.find(class_="justValue")
            parcel_id = parcel_id_el.get_text(strip=True) if parcel_id_el else ""
            if parcel_id:
                parcels.append(
                    {
                        "parcel_id": parcel_id,
                        "owner": owner_el.get_text(strip=True) if owner_el else "",
                        "just_value": value_el.get_text(strip=True) if value_el else "",
                    }
                )

        if not parcels:
            # Generic table fallback
            for row in soup.select("table tbody tr"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    parcel_id = cells[0].get_text(strip=True)
                    if parcel_id and parcel_id.lower() not in ("parcel id", "parcel #", ""):
                        parcels.append(
                            {
                                "parcel_id": parcel_id,
                                "owner": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                                "just_value": cells[2].get_text(strip=True)
                                if len(cells) > 2
                                else "",
                            }
                        )

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
