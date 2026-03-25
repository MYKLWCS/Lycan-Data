"""
redfin_property.py — Redfin property data crawler.

Queries Redfin's internal GIS API for property data by address.
Registered as "redfin_property".
"""

from __future__ import annotations

import json
import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_REDFIN_URL = (
    "https://www.redfin.com/stingray/api/gis"
    "?al=1&market=us&num_homes=5&page_number=0"
    "&region_id=&region_type=&q={address}"
)


@register("redfin_property")
class RedfinPropertyCrawler(HttpxCrawler):
    """
    Queries Redfin's internal GIS API for property data by address.
    identifier: street address (e.g. "123 Main St Dallas TX")
    """

    platform = "redfin_property"
    SOURCE_RELIABILITY = 0.70
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        url = _REDFIN_URL.format(address=quote_plus(address))
        resp = await self.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.redfin.com/",
            },
        )
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            # Redfin prepends "{}&&" to prevent JSON hijacking
            raw_text = resp.text
            if raw_text.startswith("{}&&"):
                raw_text = raw_text[4:]
            payload = json.loads(raw_text)
        except Exception as exc:
            logger.debug("Redfin JSON parse error for %s: %s", identifier, exc)
            # Fallback: try resp.json() directly
            try:
                payload = resp.json()
            except Exception:
                return self._result(identifier, found=False, error="parse_error")

        homes_raw = (payload.get("payload") or {}).get("homes") or []
        if not homes_raw:
            return self._result(identifier, found=False)

        properties = []
        for h in homes_raw[:10]:
            addr = h.get("address") or {}
            properties.append({
                "address": f"{addr.get('streetAddress', '')} {addr.get('city', '')} {addr.get('state', '')} {addr.get('zip', '')}".strip(),
                "price": h.get("price"),
                "beds": h.get("beds"),
                "baths": h.get("baths"),
                "sqft": h.get("sqFt"),
                "year_built": h.get("yearBuilt"),
                "listing_type": h.get("listingType"),
            })

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"properties": properties, "count": len(properties)},
            source_reliability=self.SOURCE_RELIABILITY,
        )
