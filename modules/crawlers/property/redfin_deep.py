"""
redfin_deep.py — Deep Redfin property crawler.

Scrapes Redfin for comprehensive property data including 20+ years of sale
history, price changes, school ratings, walk/transit scores, and full
property specs.

Uses Redfin's internal stingray API (no auth required):
    /stingray/api/location/autocomplete   — address resolution
    /stingray/api/gis                     — listing search + basic data
    /stingray/do/api/home/details         — full property detail

Registered as "redfin_deep".

identifier: address string, e.g. "123 Main St Dallas TX 75201"
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_AUTOCOMPLETE_URL = (
    "https://www.redfin.com/stingray/api/location/autocomplete"
    "?location={address}&v=2&al=1&resultTypes=1"
)
_GIS_URL = (
    "https://www.redfin.com/stingray/api/gis"
    "?al=1&market=national&num_homes=5&page_number=0"
    "&region_id=&region_type=&uipt=1,2,3,4&v=8&q={address}"
)
_DETAIL_URL = (
    "https://www.redfin.com/stingray/api/home/details/belowTheFold"
    "?propertyId={property_id}&accessLevel=1&pageType=1"
)
_PRICE_HISTORY_URL = (
    "https://www.redfin.com/stingray/api/home/details/ml_history"
    "?propertyId={property_id}&accessLevel=1"
)
_XSSI_RE = re.compile(r"^\s*\{\}\s*&&\s*")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _strip_xssi(text: str) -> str:
    return _XSSI_RE.sub("", text, count=1).strip()


def _parse_json(text: str) -> dict:
    try:
        return json.loads(_strip_xssi(text))
    except Exception:
        return {}


def _money(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_autocomplete(data: dict) -> list[dict[str, Any]]:
    stubs: list[dict[str, Any]] = []
    for section in data.get("payload", {}).get("sections", []):
        for row in section.get("rows", []):
            stubs.append(
                {
                    "display": row.get("name", ""),
                    "url": row.get("url", ""),
                    "id": row.get("id", ""),
                    "type": row.get("type", ""),
                    "property_id": None,
                    "listing_id": None,
                }
            )
    return stubs


def _extract_property_id(url: str) -> str | None:
    """Pull numeric ID from a Redfin property URL slug."""
    m = re.search(r"/(\d+)(?:_zpid|$|[^/\d])", url)
    if m:
        return m.group(1)
    # Try query param
    m = re.search(r"[?&]propertyId=(\d+)", url)
    return m.group(1) if m else None


def _parse_gis(data: dict) -> list[dict[str, Any]]:
    homes_raw = (data.get("payload") or {}).get("homes") or []
    properties = []
    for h in homes_raw[:10]:
        addr = h.get("address") or {}
        url = h.get("url", "")
        properties.append(
            {
                "street_address": addr.get("streetAddress", ""),
                "city": addr.get("city", ""),
                "state": addr.get("state", ""),
                "zip_code": addr.get("zip", ""),
                "country": "US",
                "latitude": h.get("latLong", {}).get("latitude"),
                "longitude": h.get("latLong", {}).get("longitude"),
                "property_type": h.get("homeType"),
                "current_market_value_usd": _money(h.get("price")),
                "bedrooms": h.get("beds"),
                "bathrooms_full": h.get("baths"),
                "sq_ft_living": h.get("sqFt"),
                "year_built": h.get("yearBuilt"),
                "last_sale_price_usd": _money(h.get("lastSoldPrice")),
                "last_sale_date": h.get("lastSoldDate"),
                "redfin_url": f"https://www.redfin.com{url}" if url else None,
                "property_id": h.get("propertyId") or _extract_property_id(url),
                "mls_id": h.get("mlsId"),
            }
        )
    return properties


def _parse_detail(data: dict) -> dict[str, Any]:
    """Parse the belowTheFold detail API response."""
    details: dict[str, Any] = {}
    try:
        payload = data.get("payload") or {}

        # Public record section
        pub = payload.get("publicRecordsInfo") or {}
        details["parcel_number"] = pub.get("apn")
        details["county"] = pub.get("countyFips")
        details["zoning"] = pub.get("zoning")
        details["flood_zone"] = pub.get("floodZoneDescription")
        details["sq_ft_lot"] = pub.get("lotSqFt")
        details["stories"] = pub.get("numStories")
        details["garage_spaces"] = pub.get("numParkingGarage")
        details["has_pool"] = pub.get("hasPool")
        details["current_assessed_value_usd"] = _money(pub.get("assessedValue"))
        details["current_tax_annual_usd"] = _money(pub.get("taxAmount"))

        # Owner / occupancy
        details["owner_name"] = pub.get("ownerName")
        details["owner_mailing_address"] = pub.get("ownerAddress")
        details["is_owner_occupied"] = pub.get("ownerOccupied")
        details["homestead_exemption"] = pub.get("homesteadExemption")

        # Schools
        schools = payload.get("schoolsInfo", {}).get("servingThisHome") or []
        if schools:
            details["school_district"] = schools[0].get("districtName")
        else:
            details["school_district"] = None

        # Walk / transit scores
        scores = payload.get("walkScore") or {}
        details["walk_score"] = scores.get("walkScore")
        details["transit_score"] = scores.get("transitScore")
        details["bike_score"] = scores.get("bikeScore")

        # Mortgages from public records
        mortgages = []
        for loan in pub.get("mortgageHistory") or []:
            mortgages.append(
                {
                    "lender_name": loan.get("lenderName"),
                    "loan_type": loan.get("loanType"),
                    "original_loan_amount_usd": _money(loan.get("loanAmount")),
                    "origination_date": loan.get("originationDate"),
                    "is_active": loan.get("isActive"),
                }
            )
        details["mortgages"] = mortgages

    except Exception as exc:
        logger.debug("Redfin detail parse error: %s", exc)

    return details


def _parse_price_history(data: dict) -> list[dict[str, Any]]:
    """Build ownership_history from Redfin ML history response."""
    history: list[dict[str, Any]] = []
    try:
        rows = (data.get("payload") or {}).get("rows") or []
        for row in rows:
            event_type = row.get("eventName") or row.get("source", "")
            price = _money(row.get("price"))
            history.append(
                {
                    "owner_name": None,
                    "owner_type": None,
                    "acquisition_date": row.get("soldDate") or row.get("date"),
                    "disposition_date": None,
                    "acquisition_price_usd": price if "sold" in event_type.lower() else None,
                    "acquisition_type": event_type,
                    "document_number": row.get("documentNumber"),
                    "grantor": row.get("sellerName"),
                    "grantee": row.get("buyerName"),
                    "loan_amount_usd": _money(row.get("loanAmount")),
                }
            )
    except Exception as exc:
        logger.debug("Redfin price history parse error: %s", exc)
    return history


def _parse_tax_history(detail_data: dict) -> list[dict[str, Any]]:
    valuations: list[dict[str, Any]] = []
    try:
        rows = (detail_data.get("payload") or {}).get("publicRecordsInfo", {}).get(
            "taxHistories"
        ) or []
        for row in rows:
            valuations.append(
                {
                    "valuation_year": row.get("taxYear"),
                    "assessed_value_usd": _money(row.get("assessedValue")),
                    "market_value_usd": _money(row.get("marketValue")),
                    "tax_amount_usd": _money(row.get("taxAmount")),
                }
            )
    except Exception as exc:
        logger.debug("Redfin tax history parse error: %s", exc)
    return valuations


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("redfin_deep")
class RedfinDeepCrawler(HttpxCrawler):
    """
    Deep Redfin property crawler. Returns 20+ years of sale history,
    school ratings, walk scores, owner info, and full parcel data.

    identifier: address string, e.g. "123 Main St Dallas TX"

    source_reliability: 0.82
    proxy_tier: residential
    """

    platform = "redfin_deep"
    category = CrawlerCategory.PROPERTY
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.82
    requires_tor = True
    proxy_tier = "residential"
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        encoded = quote_plus(address)

        # Step 1: autocomplete
        ac_url = _AUTOCOMPLETE_URL.format(address=encoded)
        ac_resp = await self.get(ac_url, headers=_BROWSER_HEADERS)
        autocomplete_stubs: list[dict[str, Any]] = []
        if ac_resp and ac_resp.status_code == 200:
            autocomplete_stubs = _parse_autocomplete(_parse_json(ac_resp.text))

        # Step 2: GIS search for base property data
        gis_url = _GIS_URL.format(address=encoded)
        gis_resp = await self.get(gis_url, headers=_BROWSER_HEADERS)
        if gis_resp is None or gis_resp.status_code not in (200, 206):
            return self._result(identifier, found=False, properties=[], query=address)

        properties = _parse_gis(_parse_json(gis_resp.text))
        if not properties:
            return self._result(identifier, found=False, properties=[], query=address)

        # Step 3: enrich each property with full detail + price history
        for prop in properties[:3]:
            pid = prop.get("property_id")
            if not pid:
                # try to pull from autocomplete
                for stub in autocomplete_stubs:
                    prop_id = _extract_property_id(stub.get("url", ""))
                    if prop_id:  # pragma: no branch
                        pid = prop_id
                        break
            if pid:
                detail_data = await self._fetch_detail(pid)
                hist_data = await self._fetch_price_history(pid)
                prop.update(detail_data)
                prop["ownership_history"] = _parse_price_history(hist_data)
                prop["valuations"] = _parse_tax_history(detail_data)

        return self._result(
            identifier,
            found=True,
            properties=properties,
            query=address,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_detail(self, property_id: str) -> dict[str, Any]:
        url = _DETAIL_URL.format(property_id=property_id)
        try:
            resp = await self.get(url, headers=_BROWSER_HEADERS)
            if resp and resp.status_code == 200:
                return _parse_detail(_parse_json(resp.text))
        except Exception as exc:
            logger.debug("Redfin detail fetch error pid=%s: %s", property_id, exc)
        return {}

    async def _fetch_price_history(self, property_id: str) -> dict[str, Any]:
        url = _PRICE_HISTORY_URL.format(property_id=property_id)
        try:
            resp = await self.get(url, headers=_BROWSER_HEADERS)
            if resp and resp.status_code == 200:
                return _parse_json(resp.text)
        except Exception as exc:
            logger.debug("Redfin price history fetch error pid=%s: %s", property_id, exc)
        return {}
