"""
attom_gateway.py — ATTOM property-report crawler.

Lycan runs this crawler in free-only mode. The live scrape path uses the
public ATTOM property-report portal and ignores any configured commercial
ATTOM API key so the repo does not depend on paid data access.

Registered as "attom_gateway".

identifier: address string or APN, e.g.:
    "123 Main St, Dallas TX 75001"
    "APN:123-456-789 TX"
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from shared.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

_API_BASE = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"
_API_PROPERTY_DETAIL = f"{_API_BASE}/property/detail"
_API_PROPERTY_OWNER = f"{_API_BASE}/property/expandedprofile"
_API_SALE_HISTORY = f"{_API_BASE}/saleshistory/detail"
_API_AVM = f"{_API_BASE}/avm/detail"
_API_FORECLOSURE = f"{_API_BASE}/property/foreclosure"

# Public portal (no auth)
_PUBLIC_SEARCH = "https://www.attomdata.com/property-report/?address={query}"
_PROPSTREAM_SEARCH = "https://app.propstream.com/api/search?q={query}"

_API_HEADERS = {
    "Accept": "application/json",
    "apikey": "",  # populated dynamically
}
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.attomdata.com/",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _money(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_api_property(data: dict) -> dict[str, Any]:
    """Parse ATTOM REST API property/detail response."""
    prop: dict[str, Any] = {}
    try:
        item = (data.get("property") or [{}])[0]
        addr = item.get("address", {})
        building = item.get("building", {})
        lot = item.get("lot", {})
        assess = item.get("assessment", {})
        tax = item.get("tax", {})
        sale = item.get("sale", {})
        owner = item.get("owner", {})

        prop["parcel_number"] = item.get("identifier", {}).get("apn")
        prop["attom_id"] = item.get("identifier", {}).get("attomId")
        prop["street_address"] = addr.get("line1", "")
        prop["city"] = addr.get("locality", "")
        prop["state"] = addr.get("countrySubd", "")
        prop["zip_code"] = addr.get("postal1", "")
        prop["county"] = addr.get("subdCd", "")
        prop["country"] = addr.get("country", "US")
        prop["latitude"] = item.get("location", {}).get("latitude")
        prop["longitude"] = item.get("location", {}).get("longitude")

        prop["property_type"] = building.get("summary", {}).get("propType")
        prop["sub_type"] = building.get("summary", {}).get("propSubType")
        prop["year_built"] = building.get("summary", {}).get("yearBuilt")
        prop["sq_ft_living"] = building.get("size", {}).get("livingSize")
        prop["sq_ft_lot"] = lot.get("lotSize1")
        prop["bedrooms"] = building.get("rooms", {}).get("beds")
        prop["bathrooms_full"] = building.get("rooms", {}).get("bathsFull")
        prop["bathrooms_half"] = building.get("rooms", {}).get("bathsHalf")
        prop["stories"] = building.get("summary", {}).get("levels")
        prop["garage_spaces"] = building.get("parking", {}).get("garageSpaces")
        prop["has_pool"] = building.get("amenities", {}).get("pool")
        prop["zoning"] = lot.get("zoningType")
        prop["flood_zone"] = lot.get("floodZone")
        prop["school_district"] = None  # Not in basic detail

        prop["current_assessed_value_usd"] = _money(assess.get("assessed", {}).get("assdTtlValue"))
        prop["current_market_value_usd"] = _money(assess.get("market", {}).get("mktTtlValue"))
        prop["current_tax_annual_usd"] = _money(tax.get("taxAmt"))

        prop["last_sale_date"] = sale.get("salesSearchDate")
        prop["last_sale_price_usd"] = _money(sale.get("salesAmt"))
        prop["last_sale_type"] = sale.get("deedType")

        prop["owner_name"] = owner.get("owner1", {}).get("fullName")
        prop["owner_mailing_address"] = None
        prop["is_owner_occupied"] = owner.get("ownerOccupied") == "Y"
        prop["homestead_exemption"] = None

        # Distressed flags
        prop["is_distressed"] = item.get("isDistressed")
        prop["pre_foreclosure"] = item.get("inForeclosure")
        prop["is_vacant"] = item.get("isVacant")

        prop["ownership_history"] = []
        prop["valuations"] = []
        prop["mortgages"] = []

    except Exception as exc:
        logger.debug("ATTOM API property parse error: %s", exc)

    return prop


def _parse_api_sale_history(data: dict, prop: dict) -> dict:
    """Merge sale history into prop dict."""
    try:
        for sale in data.get("property") or []:
            for event in sale.get("saleHistory") or []:
                prop["ownership_history"].append(
                    {
                        "owner_name": event.get("buyerName"),
                        "owner_type": None,
                        "acquisition_date": event.get("saleTransDate"),
                        "disposition_date": None,
                        "acquisition_price_usd": _money(event.get("amount")),
                        "acquisition_type": event.get("deedType"),
                        "document_number": event.get("docNumber"),
                        "grantor": event.get("sellerName"),
                        "grantee": event.get("buyerName"),
                        "loan_amount_usd": _money(event.get("loanAmount")),
                    }
                )
    except Exception as exc:
        logger.debug("ATTOM sale history parse error: %s", exc)
    return prop


def _parse_api_avm(data: dict, prop: dict) -> dict:
    """Merge AVM valuation into prop dict."""
    try:
        item = (data.get("property") or [{}])[0]
        avm = item.get("avm", {})
        prop["avm_value_usd"] = _money(avm.get("amount", {}).get("value"))
        prop["avm_low_usd"] = _money(avm.get("amount", {}).get("low"))
        prop["avm_high_usd"] = _money(avm.get("amount", {}).get("high"))
        prop["avm_confidence"] = avm.get("eventType")
        # Override market value with AVM if not already set
        if not prop.get("current_market_value_usd") and prop.get("avm_value_usd"):
            prop["current_market_value_usd"] = prop["avm_value_usd"]
    except Exception as exc:
        logger.debug("ATTOM AVM parse error: %s", exc)
    return prop


def _parse_public_portal_html(html: str) -> dict[str, Any]:
    """Parse ATTOM public property report page (no auth)."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    prop: dict[str, Any] = {
        "parcel_number": None,
        "street_address": None,
        "city": None,
        "state": None,
        "zip_code": None,
        "property_type": None,
        "year_built": None,
        "sq_ft_living": None,
        "bedrooms": None,
        "bathrooms_full": None,
        "current_assessed_value_usd": None,
        "current_market_value_usd": None,
        "current_tax_annual_usd": None,
        "last_sale_date": None,
        "last_sale_price_usd": None,
        "owner_name": None,
        "ownership_history": [],
        "valuations": [],
        "mortgages": [],
    }

    patterns: dict[str, str] = {
        "parcel_number": r"(?:APN|Parcel)[:\s]+([0-9\-\.]{6,20})",
        "year_built": r"(?:Year Built|Built)[:\s]+(\d{4})",
        "sq_ft_living": r"(?:Sq\.?\s*Ft|Square\s*Feet)[:\s]+([\d,]+)",
        "bedrooms": r"Bed(?:room)?s?[:\s]+(\d+)",
        "bathrooms_full": r"Bath(?:room)?s?[:\s]+(\d+)",
        "owner_name": r"Owner[:\s]+([A-Z][A-Z\s,\.&']{3,50})(?=\s{2,}|\n)",
        "last_sale_date": r"(?:Last\s+)?Sale\s+Date[:\s]+([\d/\-]+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.I)
        if m:
            prop[key] = m.group(1).strip()

    for key in ("sq_ft_living", "bedrooms", "bathrooms_full", "year_built"):
        if prop[key]:
            try:
                prop[key] = int(str(prop[key]).replace(",", ""))
            except ValueError:
                prop[key] = None

    for label, dest_key in [
        ("assessed", "current_assessed_value_usd"),
        ("market", "current_market_value_usd"),
        ("tax", "current_tax_annual_usd"),
        ("sale price", "last_sale_price_usd"),
    ]:
        m = re.search(rf"{label}[^$\d]*\$?([\d,]{{3,12}})", text, re.I)
        if m:
            try:
                prop[dest_key] = int(m.group(1).replace(",", ""))
            except ValueError:
                prop[dest_key] = None

    return prop


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("attom_gateway")
class AttomGatewayCrawler(HttpxCrawler):
    """
    ATTOM gateway in free-only mode.

    Provides: AVM, 30+ year ownership history, MLS history, foreclosure
    data, distressed property flags.

    identifier:
        "123 Main St, Dallas TX 75001"
        "APN:123-456-789 TX"

    source_reliability: 0.95
    proxy_tier: datacenter
    """

    platform = "attom_gateway"
    category = CrawlerCategory.PROPERTY
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.95
    requires_tor = False
    proxy_tier = "datacenter"

    @property
    def _api_key(self) -> str | None:
        return getattr(settings, "attom_api_key", None) or None

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        # Strip APN: prefix if present
        clean_query = re.sub(r"^(?:APN|Parcel)[:\s]+", "", query, flags=re.I).strip()

        if self._api_key:
            logger.info("Ignoring ATTOM API key; using free public portal mode only")

        return await self._scrape_public_portal(identifier, clean_query)

    # ------------------------------------------------------------------
    # API mode
    # ------------------------------------------------------------------

    async def _scrape_via_api(self, identifier: str, query: str) -> CrawlerResult:
        logger.info("ATTOM API mode is disabled in the free-only runtime")
        return self._result(
            identifier,
            found=False,
            error="attom_api_disabled_free_only_runtime",
            query=query,
        )

    # ------------------------------------------------------------------
    # Public portal mode
    # ------------------------------------------------------------------

    async def _scrape_public_portal(self, identifier: str, query: str) -> CrawlerResult:
        url = _PUBLIC_SEARCH.format(query=quote_plus(query))
        resp = await self.get(url, headers=_BROWSER_HEADERS)
        if resp is None or resp.status_code not in (200, 206):
            return self._result(identifier, found=False, error="attom_portal_unreachable")

        prop = _parse_public_portal_html(resp.text)
        prop["country"] = "US"
        prop["query"] = query

        found = bool(
            prop.get("parcel_number")
            or prop.get("current_assessed_value_usd")
            or prop.get("current_market_value_usd")
            or prop.get("owner_name")
        )

        return self._result(
            identifier,
            found=found,
            properties=[prop] if found else [],
            query=query,
            source="attom_portal",
        )
