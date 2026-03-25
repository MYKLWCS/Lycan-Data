"""
propertyradar_scraper.py — PropertyRadar.com public search crawler.

PropertyRadar aggregates county assessor, recorder, and MLS data.
The public search returns all properties owned by a given person,
with owner-level and property-level flags including:
    - Pre-foreclosure
    - Tax default
    - LLC / corporate ownership
    - Absentee owner
    - Vacant

Scrapes PropertyRadar's public owner search and individual property
detail pages.

Registered as "propertyradar_scraper".

identifier: person name + state, e.g.
    "John Smith CA"
    "Smith, John | TX"
    "John Smith | Los Angeles CA"
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://www.propertyradar.com/app/search?name={name}&state={state}"
_OWNER_API = "https://www.propertyradar.com/api/owners?name={name}&state={state}&limit=10"
_PROPERTY_API = "https://www.propertyradar.com/api/properties?ownerId={owner_id}&limit=25"
_PROPERTY_DETAIL = "https://www.propertyradar.com/property/{property_id}"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.propertyradar.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Returns (name, state, city_hint).
    Handles:
        "John Smith CA"
        "Smith, John | TX"
        "John Smith | Los Angeles CA"
    """
    if "|" in identifier:
        parts = [p.strip() for p in identifier.split("|", 1)]
        name = parts[0]
        loc = parts[1].strip()
        # "Los Angeles CA" or just "CA"
        m = re.match(r"^(.*?)\s+([A-Z]{2})$", loc)
        if m:
            return name, m.group(2).upper(), m.group(1).strip()
        if re.match(r"^[A-Z]{2}$", loc):
            return name, loc.upper(), ""
        return name, "", loc
    # "John Smith CA" or "John Smith Los Angeles CA"
    m = re.search(r"\b([A-Z]{2})\s*$", identifier.strip())
    if m:
        state = m.group(1).upper()
        rest = identifier[: m.start()].strip()
        return rest, state, ""
    return identifier.strip(), "", ""


# ---------------------------------------------------------------------------
# Money / value helpers
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


def _bool_flag(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "yes", "1", "y")
    return bool(val)


# ---------------------------------------------------------------------------
# API / HTML parsers
# ---------------------------------------------------------------------------


def _parse_owner_api(data: dict | list) -> list[dict[str, Any]]:
    """Parse PropertyRadar owner search API response."""
    if isinstance(data, list):
        owners = data
    else:
        owners = data.get("owners") or data.get("results") or []
    result = []
    for o in owners[:10]:
        result.append(
            {
                "owner_id": o.get("ownerId") or o.get("id"),
                "owner_name": o.get("name") or o.get("ownerName"),
                "owner_type": o.get("ownerType"),
                "property_count": o.get("propertyCount"),
                "estimated_equity": _money(o.get("equity")),
                "portfolio_value": _money(o.get("totalValue")),
                "state": o.get("state"),
            }
        )
    return result


def _parse_property_api(data: dict | list) -> list[dict[str, Any]]:
    """Parse PropertyRadar property list for an owner."""
    if isinstance(data, list):
        items = data
    else:
        items = data.get("properties") or data.get("results") or []

    properties = []
    for item in items[:25]:
        prop: dict[str, Any] = {
            "parcel_number": item.get("apn") or item.get("parcelNumber"),
            "property_id": item.get("propertyId") or item.get("id"),
            "street_address": item.get("address") or item.get("streetAddress"),
            "city": item.get("city"),
            "state": item.get("state"),
            "zip_code": item.get("zip") or item.get("postalCode"),
            "county": item.get("county"),
            "country": "US",
            "latitude": item.get("lat") or item.get("latitude"),
            "longitude": item.get("lng") or item.get("longitude"),
            "property_type": item.get("useType") or item.get("propertyType"),
            "year_built": item.get("yearBuilt"),
            "sq_ft_living": item.get("buildingSqFt") or item.get("sqFt"),
            "sq_ft_lot": item.get("lotSqFt"),
            "bedrooms": item.get("beds") or item.get("bedrooms"),
            "bathrooms_full": item.get("baths") or item.get("bathrooms"),
            "bathrooms_half": item.get("bathsHalf"),
            "stories": item.get("stories"),
            "garage_spaces": item.get("garageSpaces"),
            "has_pool": _bool_flag(item.get("hasPool")),
            "zoning": item.get("zoning"),
            "flood_zone": item.get("floodZone"),
            "school_district": item.get("schoolDistrict"),
            # Valuation
            "current_assessed_value_usd": _money(item.get("assessedValue")),
            "current_market_value_usd": _money(item.get("estimatedValue") or item.get("avm")),
            "current_tax_annual_usd": _money(item.get("taxAmount")),
            "last_sale_date": item.get("lastSaleDate"),
            "last_sale_price_usd": _money(item.get("lastSaleAmount")),
            "last_sale_type": item.get("lastSaleType"),
            # Owner
            "owner_name": item.get("ownerName"),
            "owner_mailing_address": item.get("mailingAddress"),
            "is_owner_occupied": _bool_flag(item.get("ownerOccupied")),
            "homestead_exemption": _bool_flag(item.get("homesteadExemption")),
            # PropertyRadar-specific flags
            "is_pre_foreclosure": _bool_flag(
                item.get("preForeclosure") or item.get("inForeclosure")
            ),
            "is_tax_default": _bool_flag(item.get("taxDefault") or item.get("taxDelinquent")),
            "is_llc_owned": _bool_flag(item.get("llcOwned") or item.get("corporateOwned")),
            "is_absentee_owner": _bool_flag(item.get("absenteeOwner")),
            "is_vacant": _bool_flag(item.get("vacant") or item.get("isVacant")),
            # Equity
            "estimated_equity_usd": _money(item.get("equity")),
            "equity_percent": item.get("equityPercent"),
            # History placeholders
            "ownership_history": [],
            "valuations": [],
            "mortgages": [],
        }
        # Mortgages
        for loan in item.get("mortgages") or []:
            prop["mortgages"].append(
                {
                    "lender_name": loan.get("lenderName"),
                    "loan_type": loan.get("loanType"),
                    "original_loan_amount_usd": _money(loan.get("loanAmount")),
                    "origination_date": loan.get("originationDate"),
                    "is_active": loan.get("isActive"),
                }
            )
        properties.append(prop)
    return properties


def _parse_search_html(html: str, state: str) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Parse PropertyRadar search results page (public-facing HTML).
    Returns (owner_stubs, property_ids).
    """
    soup = BeautifulSoup(html, "html.parser")
    owners: list[dict[str, Any]] = []
    property_ids: list[str] = []

    # Try JSON embedded in page
    try:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});", html, re.DOTALL)
        if m:
            page_data = json.loads(m.group(1))
            owner_data = page_data.get("search", {}).get("owners") or page_data.get("owners") or []
            if owner_data:  # pragma: no branch
                owners = _parse_owner_api(owner_data)
    except Exception:
        pass

    # HTML table fallback
    if not owners:
        for row in soup.select("table.owner-results tr, .owner-card, .search-result"):
            name_el = row.find(class_=re.compile(r"owner.?name", re.I)) or row.find("td")
            if name_el:  # pragma: no branch
                name_text = name_el.get_text(strip=True)
                if name_text and name_text.lower() not in ("name", "owner"):
                    owners.append(
                        {
                            "owner_id": None,
                            "owner_name": name_text,
                            "owner_type": None,
                            "property_count": None,
                            "state": state,
                        }
                    )

    # Property ID links
    for link in soup.find_all("a", href=re.compile(r"/property/\d+")):
        pid_m = re.search(r"/property/(\d+)", link.get("href", ""))
        if pid_m:  # pragma: no branch
            property_ids.append(pid_m.group(1))

    return owners, property_ids


def _parse_property_detail_html(html: str) -> dict[str, Any]:
    """Parse a PropertyRadar property detail page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    prop: dict[str, Any] = {
        "parcel_number": None,
        "street_address": None,
        "city": None,
        "state": None,
        "zip_code": None,
        "county": None,
        "owner_name": None,
        "current_assessed_value_usd": None,
        "current_market_value_usd": None,
        "current_tax_annual_usd": None,
        "last_sale_date": None,
        "last_sale_price_usd": None,
        "year_built": None,
        "sq_ft_living": None,
        "bedrooms": None,
        "bathrooms_full": None,
        "is_pre_foreclosure": False,
        "is_tax_default": False,
        "is_absentee_owner": False,
        "is_vacant": False,
        "is_llc_owned": False,
        "estimated_equity_usd": None,
        "ownership_history": [],
        "valuations": [],
        "mortgages": [],
    }

    # Try JSON embedded state
    try:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});", html, re.DOTALL)
        if m:
            page_data = json.loads(m.group(1))
            property_data = page_data.get("property") or {}
            if property_data:
                props = _parse_property_api([property_data])
                if props:  # pragma: no branch
                    return props[0]
    except Exception:
        pass

    # Regex extraction fallback
    patterns = {
        "parcel_number": r"(?:APN|Parcel)[:\s]+([0-9\-\.]{6,20})",
        "year_built": r"Year\s+Built[:\s]+(\d{4})",
        "sq_ft_living": r"(?:Sq\.?\s*Ft|Building)[:\s]+([\d,]+)",
        "bedrooms": r"Bed(?:room)?s?[:\s]+(\d+)",
        "bathrooms_full": r"Bath(?:room)?s?[:\s]+(\d+)",
        "owner_name": r"Owner[:\s]+([A-Z][A-Z\s,\.&']{3,50}?)(?=\s{2,}|\n|$)",
        "last_sale_date": r"(?:Last\s+)?Sale\s+Date[:\s]+([\d/\-]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            prop[key] = match.group(1).strip()

    for int_key in ("year_built", "sq_ft_living", "bedrooms", "bathrooms_full"):
        if prop[int_key]:
            try:
                prop[int_key] = int(str(prop[int_key]).replace(",", ""))
            except ValueError:
                prop[int_key] = None

    for label, dest in [
        ("assessed", "current_assessed_value_usd"),
        ("market|estimated", "current_market_value_usd"),
        ("tax", "current_tax_annual_usd"),
        ("sale price|sold for", "last_sale_price_usd"),
        ("equity", "estimated_equity_usd"),
    ]:
        m2 = re.search(rf"(?:{label})[^$\d]*\$?([\d,]{{3,12}})", text, re.I)
        if m2:
            try:
                prop[dest] = int(m2.group(1).replace(",", ""))
            except ValueError:
                pass

    # Flags
    text_lower = text.lower()
    prop["is_pre_foreclosure"] = (
        "pre-foreclosure" in text_lower or "notice of default" in text_lower
    )
    prop["is_tax_default"] = "tax default" in text_lower or "tax delinquent" in text_lower
    prop["is_absentee_owner"] = "absentee" in text_lower
    prop["is_vacant"] = "vacant" in text_lower
    prop["is_llc_owned"] = bool(re.search(r"\bllc\b|\bcorp\b|\binc\b", text, re.I))

    return prop


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("propertyradar_scraper")
class PropertyRadarCrawler(HttpxCrawler):
    """
    Scrapes PropertyRadar.com for owner-level property portfolio data.
    Returns all properties owned by a person with distressed/flag data.

    identifier:
        "John Smith CA"
        "Smith, John | TX"
        "John Smith | Los Angeles CA"

    source_reliability: 0.85
    proxy_tier: residential
    """

    platform = "propertyradar_scraper"
    source_reliability = 0.85
    requires_tor = True
    proxy_tier = "residential"
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        name, state, city_hint = _parse_identifier(identifier)

        if not name:
            return self._result(identifier, found=False, error="name_required")
        if not state:
            return self._result(
                identifier, found=False, error="state_required — append state abbr to identifier"
            )

        encoded_name = quote_plus(name)

        # Step 1: try owner API endpoint
        api_url = _OWNER_API.format(name=encoded_name, state=state.lower())
        api_resp = await self.get(api_url, headers=_BROWSER_HEADERS)

        owners: list[dict[str, Any]] = []
        property_ids: list[str] = []

        if api_resp and api_resp.status_code == 200:
            try:
                owners = _parse_owner_api(api_resp.json())
            except Exception as exc:
                logger.debug("PropertyRadar owner API parse error: %s", exc)

        # Step 2: if API didn't work, fall back to HTML search
        if not owners:
            search_url = _SEARCH_URL.format(name=encoded_name, state=state.lower())
            search_resp = await self.get(search_url, headers=_BROWSER_HEADERS)
            if search_resp and search_resp.status_code == 200:
                owners, property_ids = _parse_search_html(search_resp.text, state)

        if not owners and not property_ids:
            return self._result(identifier, found=False, properties=[], query=name, state=state)

        # Step 3: fetch properties for each owner
        all_properties: list[dict[str, Any]] = []

        for owner in owners[:3]:
            owner_id = owner.get("owner_id")
            if owner_id:
                props_url = _PROPERTY_API.format(owner_id=owner_id)
                props_resp = await self.get(props_url, headers=_BROWSER_HEADERS)
                if props_resp and props_resp.status_code == 200:
                    try:
                        props = _parse_property_api(props_resp.json())
                        # Attach owner meta to each property
                        for p in props:
                            p["owner_name"] = p.get("owner_name") or owner.get("owner_name")
                            p["is_llc_owned"] = p.get("is_llc_owned") or (
                                bool(
                                    re.search(
                                        r"\bllc\b|\bcorp\b", owner.get("owner_name", ""), re.I
                                    )
                                )
                            )
                        all_properties.extend(props)
                    except Exception as exc:
                        logger.debug("PropertyRadar property API parse error: %s", exc)

        # Step 4: if we have property IDs from HTML but no API data, scrape detail pages
        if not all_properties:
            for pid in property_ids[:5]:
                detail_url = _PROPERTY_DETAIL.format(property_id=pid)
                detail_resp = await self.get(detail_url, headers=_BROWSER_HEADERS)
                if detail_resp and detail_resp.status_code == 200:
                    prop = _parse_property_detail_html(detail_resp.text)
                    prop["property_id"] = pid
                    all_properties.append(prop)

        found = len(all_properties) > 0

        return self._result(
            identifier,
            found=found,
            properties=all_properties,
            owners=owners,
            query=name,
            state=state,
            total_properties=len(all_properties),
        )
