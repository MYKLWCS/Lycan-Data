"""
zillow_deep.py — Deep Zillow property crawler.

Scrapes Zillow for comprehensive property data by address or owner name.
Uses Zillow's autocomplete API, GetSearchPageState endpoint, and property
detail pages. Extracts Zestimate, price history, tax history, ownership,
and full property specs.

Registered as "zillow_deep".

identifier formats:
    "123 Main St, Dallas, TX 75001"          — address lookup
    "owner:John Smith Dallas TX"             — owner name search
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_SUGGEST_URL = (
    "https://www.zillowstatic.com/autocomplete/v3/suggestions"
    "?q={query}&resultCount=5&resultTypes=allAddress"
)
_SEARCH_STATE_URL = (
    "https://www.zillow.com/search/GetSearchPageState.htm"
    "?searchQueryState={sqs}&wants={{%22cat1%22:[%22listResults%22,%22mapResults%22]}}"
    "&requestId=1"
)
_PROPERTY_URL = "https://www.zillow.com/homedetails/{zpid}_zpid/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
_API_HEADERS = {
    **_BROWSER_HEADERS,
    "Accept": "application/json",
    "Referer": "https://www.zillow.com/",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _money(val: Any) -> int | None:
    """Parse a money string or numeric into an integer USD amount."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_suggestions(data: dict) -> list[dict[str, Any]]:
    """Turn Zillow autocomplete results into address stubs with zpid."""
    stubs: list[dict[str, Any]] = []
    for item in data.get("results", [])[:8]:
        meta = item.get("metaData", {})
        stubs.append(
            {
                "display": item.get("display", ""),
                "street_address": meta.get("streetAddress", ""),
                "city": meta.get("addressCity", ""),
                "state": meta.get("addressState", ""),
                "zip_code": meta.get("addressZip", ""),
                "latitude": meta.get("lat"),
                "longitude": meta.get("lng"),
                "zpid": meta.get("zpid"),
            }
        )
    return stubs


def _parse_price_history(history: list[dict]) -> list[dict[str, Any]]:
    """Normalise Zillow priceHistory array into ownership_history entries."""
    result = []
    for h in history or []:
        event = h.get("event", "")
        price = _money(h.get("price"))
        date = h.get("date") or h.get("time")
        # Interpret sold events as ownership transfers
        if "sold" in event.lower() or price:
            result.append(
                {
                    "owner_name": None,
                    "owner_type": None,
                    "acquisition_date": date,
                    "disposition_date": None,
                    "acquisition_price_usd": price
                    if "sold" in event.lower() or "bought" in event.lower()
                    else None,
                    "acquisition_type": event,
                    "document_number": None,
                    "grantor": None,
                    "grantee": None,
                    "loan_amount_usd": None,
                }
            )
    return result


def _parse_tax_history(history: list[dict]) -> list[dict[str, Any]]:
    """Normalise Zillow taxHistory array into valuations entries."""
    result = []
    for h in history or []:
        year = h.get("taxPaidYear") or h.get("time")
        # year may be a timestamp string — extract 4-digit year
        if year and not isinstance(year, int):
            m = re.search(r"(\d{4})", str(year))
            year = int(m.group(1)) if m else None
        result.append(
            {
                "valuation_year": year,
                "assessed_value_usd": _money(h.get("value")),
                "market_value_usd": _money(h.get("value")),
                "tax_amount_usd": _money(h.get("taxPaid")),
            }
        )
    return result


def _parse_next_data(html: str) -> dict[str, Any]:
    """
    Extract the __NEXT_DATA__ JSON blob from a Zillow property page.
    Returns a flat property dict with as many fields as can be parsed.
    """
    details: dict[str, Any] = {}
    try:
        m = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            return details

        page_data = json.loads(m.group(1))
        # Navigate the nested page props
        gdp_cache = (
            page_data.get("props", {})
            .get("pageProps", {})
            .get("componentProps", {})
            .get("gdpClientCache", {})
        )
        if isinstance(gdp_cache, str):  # pragma: no branch
            gdp_cache = json.loads(gdp_cache)

        # gdpClientCache is keyed by zpid or random key; iterate to find property
        home: dict[str, Any] = {}
        for _key, val in gdp_cache.items():
            if isinstance(val, dict) and "property" in val:
                home = val["property"]
                break
            elif isinstance(val, dict) and "bedrooms" in val:
                home = val
                break

        if not home:
            return details

        addr = home.get("address", {})
        details["street_address"] = addr.get("streetAddress", "")
        details["city"] = addr.get("city", "")
        details["state"] = addr.get("state", "")
        details["zip_code"] = addr.get("zipcode", "")
        details["country"] = "US"
        details["latitude"] = home.get("latitude")
        details["longitude"] = home.get("longitude")
        details["parcel_number"] = home.get("parcelId")
        details["property_type"] = home.get("homeType", "")
        details["year_built"] = home.get("yearBuilt")
        details["sq_ft_living"] = home.get("livingArea")
        details["sq_ft_lot"] = home.get("lotSize")
        details["bedrooms"] = home.get("bedrooms")
        details["bathrooms_full"] = home.get("bathrooms")
        details["bathrooms_half"] = None
        details["stories"] = home.get("stories")
        details["garage_spaces"] = home.get("garageParkingSpaces")
        details["has_pool"] = home.get("hasPool") or home.get("poolFeatures") is not None
        details["zoning"] = home.get("zoning")
        details["flood_zone"] = home.get("floodZoneDescription")
        details["school_district"] = (
            (home.get("schools") or [{}])[0].get("districtName") if home.get("schools") else None
        )
        details["current_assessed_value_usd"] = _money(home.get("assessorLastSalePrice"))
        details["current_market_value_usd"] = _money(home.get("zestimate"))
        details["current_tax_annual_usd"] = _money(
            home.get("annualHomeownersInsurance")
        )  # best proxy available

        # Last sale
        price_hist = home.get("priceHistory", [])
        for event in price_hist:
            if "sold" in (event.get("event") or "").lower():  # pragma: no branch
                details["last_sale_date"] = event.get("date")
                details["last_sale_price_usd"] = _money(event.get("price"))
                details["last_sale_type"] = event.get("event")
                break

        # Owner
        details["owner_name"] = home.get("ownerName")
        details["owner_mailing_address"] = None
        details["is_owner_occupied"] = home.get("ownerOccupied")
        details["homestead_exemption"] = None

        # History lists
        details["ownership_history"] = _parse_price_history(price_hist)
        details["valuations"] = _parse_tax_history(home.get("taxHistory", []))
        details["mortgages"] = []

        # Zestimate
        details["zestimate_usd"] = _money(home.get("zestimate"))
        details["zestimate_low_usd"] = _money(
            home.get("zestimateLowPercent") or home.get("zestimateValueChange")
        )

    except Exception as exc:
        logger.debug("Zillow __NEXT_DATA__ parse error: %s", exc)

    return details


def _parse_next_data_fallback_regex(html: str) -> dict[str, Any]:
    """Regex fallback when JSON parse fails."""
    details: dict[str, Any] = {}
    patterns = {
        "bedrooms": r'"bedrooms"\s*:\s*(\d+)',
        "bathrooms_full": r'"bathrooms"\s*:\s*([\d.]+)',
        "sq_ft_living": r'"livingArea"\s*:\s*(\d+)',
        "year_built": r'"yearBuilt"\s*:\s*(\d{4})',
        "current_market_value_usd": r'"zestimate"\s*:\s*(\d+)',
        "last_sale_price_usd": r'"lastSoldPrice"\s*:\s*(\d+)',
        "last_sale_date": r'"lastSoldDate"\s*:\s*"([^"]+)"',
        "owner_name": r'"ownerName"\s*:\s*"([^"]+)"',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, html)
        if m:
            val = m.group(1)
            if key in (
                "bedrooms",
                "sq_ft_living",
                "year_built",
                "current_market_value_usd",
                "last_sale_price_usd",
            ):
                try:
                    details[key] = int(val)
                except ValueError:
                    details[key] = val
            elif key == "bathrooms_full":
                try:
                    details[key] = float(val)
                except ValueError:
                    details[key] = val
            else:
                details[key] = val
    return details


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("zillow_deep")
class ZillowDeepCrawler(HttpxCrawler):
    """
    Deep Zillow property crawler. Returns comprehensive property data
    including Zestimate, price history, tax history, and ownership.

    identifier:
        "123 Main St, Dallas, TX 75001"    — address lookup
        "owner:John Smith Dallas TX"        — owner name search

    Returns: properties=[list of full property dicts]
    source_reliability: 0.80
    proxy_tier: residential (Zillow bans datacenter IPs aggressively)
    """

    platform = "zillow_deep"
    category = CrawlerCategory.PROPERTY
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.80
    requires_tor = True
    proxy_tier = "residential"
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        # Resolve owner-name prefix vs. direct address
        is_owner_search = query.lower().startswith("owner:")
        search_term = query[6:].strip() if is_owner_search else query

        # Step 1: autocomplete to get zpid + location stubs
        suggest_url = _SUGGEST_URL.format(query=quote_plus(search_term))
        resp = await self.get(suggest_url, headers=_API_HEADERS)
        if resp is None or resp.status_code != 200:
            return self._result(identifier, found=False, properties=[], query=query)

        try:
            suggestions = _parse_suggestions(resp.json())
        except Exception as exc:
            logger.debug("Zillow suggestions parse error: %s", exc)
            suggestions = []

        if not suggestions:
            return self._result(identifier, found=False, properties=[], query=query)

        # Step 2: enrich each stub (up to 3) with full property page data
        properties: list[dict[str, Any]] = []
        for stub in suggestions[:3]:
            prop = {**stub}
            zpid = stub.get("zpid")
            if zpid:
                page_data = await self._fetch_property_page(zpid)
                if page_data:  # pragma: no branch
                    prop.update(page_data)
            properties.append(prop)

        found = len(properties) > 0
        return self._result(
            identifier,
            found=found,
            properties=properties,
            query=query,
            total_found=len(suggestions),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_property_page(self, zpid: int | str) -> dict[str, Any]:
        """Fetch and parse a Zillow property detail page for a given zpid."""
        url = _PROPERTY_URL.format(zpid=zpid)
        try:
            resp = await self.get(url, headers=_BROWSER_HEADERS)
            if resp is None or resp.status_code != 200:
                return {}
            html = resp.text

            # Check for bot block page
            if "captcha" in html.lower() or "robot" in html.lower():
                logger.warning("Zillow bot-blocked on zpid=%s — rotating circuit", zpid)
                await self.rotate_circuit()
                return {}

            details = _parse_next_data(html)
            if not details:
                details = _parse_next_data_fallback_regex(html)
            details["zillow_url"] = url
            details["zpid"] = zpid
            return details
        except Exception as exc:
            logger.warning("Zillow property page error for zpid=%s: %s", zpid, exc)
            return {}
