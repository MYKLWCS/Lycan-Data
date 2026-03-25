"""
county_assessor_multi.py — Multi-state county assessor dispatcher.

Routes to the correct county assessor portal based on the state/county
in the identifier. Implements specific scraping logic for each county's
public portal.

Covered counties:
    CA: LA (LAACO), Alameda, San Diego, San Francisco, Orange, Riverside
    FL: Miami-Dade, Broward, Palm Beach, Hillsborough, Pinellas
    NY: NYC (ACRIS — all 5 boroughs)
    IL: Cook County
    AZ: Maricopa
    NV: Clark County
    WA: King County
    GA: Fulton, DeKalb
    NC: Mecklenburg
    CO: Denver, Arapahoe

Registered as "county_assessor_multi".

identifier formats:
    "John Smith | Miami-Dade FL"
    "123 Main St | Miami-Dade FL"
    "John Smith | Cook County IL"
    "123 Main St, Los Angeles CA"
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Returns (query, county, state).
    Supports: "query | county state", "query | county, state", bare address.
    """
    if "|" in identifier:
        parts = [p.strip() for p in identifier.split("|", 1)]
        query = parts[0]
        loc = parts[1]
        # "Miami-Dade FL" or "Cook County IL" or "FL"
        m = re.match(r"^(.*?)\s+([A-Z]{2})$", loc.strip())
        if m:
            county = re.sub(r"\s+County$", "", m.group(1), flags=re.I).strip().lower()
            state = m.group(2).upper()
            return query, county, state
        return query, "", loc.strip().upper()

    # Bare address — try to extract state from end
    m = re.search(r"\b([A-Z]{2})\s*(?:\d{5})?$", identifier.strip())
    if m:
        state = m.group(1).upper()
        query = identifier[: m.start()].strip().rstrip(",")
        return query, "", state

    return identifier.strip(), "", ""


def _resolve_county_key(county: str, state: str) -> str | None:
    """Map (county, state) to an internal county key."""
    county_clean = county.lower().replace("-", "_").replace(" ", "_")
    state_up = state.upper()

    # Direct match attempts
    candidate = f"{county_clean}_{state_up.lower()}"
    if candidate in _COUNTY_HANDLERS:
        return candidate

    # Partial match — check if any handler key starts with county fragment
    for key in _COUNTY_HANDLERS:
        if key.endswith(f"_{state_up.lower()}") and county_clean in key:
            return key

    # State-only fallback — pick the first registered county for that state
    for key in _COUNTY_HANDLERS:
        if key.endswith(f"_{state_up.lower()}"):
            return key

    return None


# ---------------------------------------------------------------------------
# Money / int helpers
# ---------------------------------------------------------------------------


def _money(text: str) -> int | None:
    m = re.search(r"[\d,]{3,}", text.replace("$", ""))
    if m:
        try:
            return int(m.group().replace(",", ""))
        except ValueError:
            return None
    return None


def _year(text: str) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return int(m.group()) if m else None


def _sqft(text: str) -> int | None:
    m = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sf)", text, re.I)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Per-county scraper implementations
# ---------------------------------------------------------------------------

# Each scraper is async def fn(self_crawler, query, soup, html, resp_url) -> dict


async def _scrape_la_ca(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    """LA County Assessor portal (assessor.lacounty.gov)."""
    url = f"https://portal.assessor.lacounty.gov/parcelsearch/search?search={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    try:
        data = resp.json()
        parcels = []
        for item in (data.get("parcels") or data.get("results") or [])[:10]:
            parcels.append({
                "parcel_number": item.get("ain") or item.get("parcelnumber"),
                "street_address": item.get("situs") or item.get("address"),
                "city": item.get("city", ""),
                "state": "CA",
                "county": "Los Angeles",
                "owner_name": item.get("ownerName") or item.get("owner"),
                "current_assessed_value_usd": _money(str(item.get("totalValue", ""))),
                "current_market_value_usd": _money(str(item.get("marketValue", ""))),
                "year_built": item.get("yearBuilt"),
                "sq_ft_living": item.get("sqftMain"),
                "property_type": item.get("useCode"),
                "ownership_history": [], "valuations": [], "mortgages": [],
            })
        return parcels
    except Exception:
        pass
    # HTML fallback
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CA", "Los Angeles")


async def _scrape_alameda_ca(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.acgov.org/ptax_pub_app/RealSearchInit.do?userAction=SEARCH&searchType=ADDR&searchAddr={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CA", "Alameda")


async def _scrape_san_diego_ca(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://arcc.co.san-diego.ca.us/onlinesvc/SearchParcel.aspx?address={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CA", "San Diego")


async def _scrape_sf_ca(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://sfassessor.org/parcel-search?parcel={quote_plus(query)}&addr={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CA", "San Francisco")


async def _scrape_orange_ca(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.ocassessor.gov/asp/parcel.asp?address={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CA", "Orange")


async def _scrape_riverside_ca(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://assessor.rivcoda.org/internetasmt/search?criteria.ownerName={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CA", "Riverside")


async def _scrape_miami_dade_fl(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.miamidade.gov/Apps/PA/propertysearch/Results.asp?address={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    parcels = []
    for row in soup.select("table.property-search-results tr, .search-result-item"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        folio = cells[0].get_text(strip=True)
        if not folio or "folio" in folio.lower():
            continue
        parcels.append({
            "parcel_number": folio,
            "street_address": cells[1].get_text(strip=True) if len(cells) > 1 else None,
            "city": "Miami",
            "state": "FL",
            "county": "Miami-Dade",
            "owner_name": cells[2].get_text(strip=True) if len(cells) > 2 else None,
            "current_market_value_usd": _money(cells[3].get_text()) if len(cells) > 3 else None,
            "ownership_history": [], "valuations": [], "mortgages": [],
        })
    if not parcels:
        parcels = _generic_table_parse(soup, "FL", "Miami-Dade")
    return parcels


async def _scrape_broward_fl(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.bcpa.net/RecInfo.asp?URL_Folio=0000&URL_NAME=&URL_ADDR={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "FL", "Broward")


async def _scrape_palm_beach_fl(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.pbcgov.org/papa/Asps/PropertyDetail/PropertyDetail.aspx?parcel={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "FL", "Palm Beach")


async def _scrape_hillsborough_fl(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://gis.hcpafl.org/propertysearch/#/nav/search?searchText={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "FL", "Hillsborough")


async def _scrape_pinellas_fl(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.pcpao.org/search_res.php?qval={quote_plus(query)}&searchType=addr"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "FL", "Pinellas")


async def _scrape_nyc_ny(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    """NYC ACRIS search — covers all 5 boroughs."""
    url = (
        f"https://a836-acris.nyc.gov/DS/DocumentSearch/PartyName"
        f"?housenum=&lastname={quote_plus(query)}&firstname=&doctype=DEED&partytype=2"
    )
    resp = await crawler.get(url, headers={**_BROWSER_HEADERS, "Referer": "https://a836-acris.nyc.gov/"})
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "NY", "New York City")


async def _scrape_cook_il(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.cookcountyassessor.com/address-search?address={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    try:
        data = resp.json()
        parcels = []
        for item in (data.get("pins") or data.get("results") or [])[:10]:
            parcels.append({
                "parcel_number": item.get("pin") or item.get("PIN"),
                "street_address": item.get("address") or item.get("propertyAddress"),
                "city": item.get("city", "Chicago"),
                "state": "IL",
                "county": "Cook",
                "owner_name": item.get("ownerName"),
                "current_assessed_value_usd": _money(str(item.get("assessedValue", ""))),
                "year_built": item.get("yearBuilt"),
                "ownership_history": [], "valuations": [], "mortgages": [],
            })
        if parcels:
            return parcels
    except Exception:
        pass
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "IL", "Cook")


async def _scrape_maricopa_az(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://mcassessor.maricopa.gov/mcs.php?q={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    parcels = []
    for row in soup.select(".search-result, .parcel-row, table.results tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        apn = cells[0].get_text(strip=True)
        if not apn or "apn" in apn.lower():
            continue
        parcels.append({
            "parcel_number": apn,
            "street_address": cells[1].get_text(strip=True) if len(cells) > 1 else None,
            "city": cells[2].get_text(strip=True) if len(cells) > 2 else None,
            "state": "AZ",
            "county": "Maricopa",
            "owner_name": cells[3].get_text(strip=True) if len(cells) > 3 else None,
            "current_assessed_value_usd": _money(cells[4].get_text()) if len(cells) > 4 else None,
            "ownership_history": [], "valuations": [], "mortgages": [],
        })
    if not parcels:
        parcels = _generic_table_parse(soup, "AZ", "Maricopa")
    return parcels


async def _scrape_clark_nv(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.clarkcountynv.gov/government/departments/assessor/property_search/index.php?search_str={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "NV", "Clark")


async def _scrape_king_wa(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx?search_type=address&search_str={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "WA", "King")


async def _scrape_fulton_ga(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://iaspublicaccess.fultoncountyga.gov/ias/Subscribers/FultonCountyGA/1/AccountDatalet.aspx?AccountNumber={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "GA", "Fulton")


async def _scrape_dekalb_ga(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.qpublic.net/ga/dekalb/search.html?name={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "GA", "DeKalb")


async def _scrape_mecklenburg_nc(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://polaris3g.mecklenburgcountync.gov/search/parcelsearch?s={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    try:
        data = resp.json()
        parcels = []
        for item in (data.get("features") or data.get("results") or [])[:10]:
            attr = item.get("attributes") or item
            parcels.append({
                "parcel_number": attr.get("PIN") or attr.get("pid"),
                "street_address": attr.get("FULL_ADDRESS") or attr.get("address"),
                "city": attr.get("CITY", "Charlotte"),
                "state": "NC",
                "county": "Mecklenburg",
                "owner_name": attr.get("OWNER_NAME") or attr.get("ownerName"),
                "current_assessed_value_usd": _money(str(attr.get("TOTAL_VALUE", ""))),
                "year_built": attr.get("YEAR_BUILT"),
                "sq_ft_living": attr.get("HEATED_AREA"),
                "ownership_history": [], "valuations": [], "mortgages": [],
            })
        if parcels:
            return parcels
    except Exception:
        pass
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "NC", "Mecklenburg")


async def _scrape_denver_co(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.denvergov.org/assessor/assessor/main/assessorAddress.aspx?addr={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CO", "Denver")


async def _scrape_arapahoe_co(crawler: "CountyAssessorMultiCrawler", query: str) -> list[dict[str, Any]]:
    url = f"https://www.arapahoegov.com/1297/Property-Search?search={quote_plus(query)}"
    resp = await crawler.get(url, headers=_BROWSER_HEADERS)
    if not resp or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _generic_table_parse(soup, "CO", "Arapahoe")


# ---------------------------------------------------------------------------
# Generic table parser (fallback for any county)
# ---------------------------------------------------------------------------


def _generic_table_parse(soup: BeautifulSoup, state: str, county: str) -> list[dict[str, Any]]:
    """
    Extract property rows from any standard HTML table.
    Maps common column header patterns to canonical property fields.
    """
    parcels: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not any(k in " ".join(headers) for k in ("parcel", "owner", "account", "pin", "apn", "address")):
            continue

        for row in rows[1:20]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            prop: dict[str, Any] = {
                "parcel_number": None, "street_address": None, "city": None,
                "state": state, "county": county, "country": "US",
                "owner_name": None, "current_assessed_value_usd": None,
                "current_market_value_usd": None, "current_tax_annual_usd": None,
                "year_built": None, "sq_ft_living": None, "property_type": None,
                "ownership_history": [], "valuations": [], "mortgages": [],
            }
            for i, header in enumerate(headers):
                if i >= len(cells):
                    break
                val = cells[i]
                if not val:
                    continue
                if any(k in header for k in ("parcel", "pin", "apn", "account", "folio")):
                    prop["parcel_number"] = val
                elif "address" in header:
                    prop["street_address"] = val
                elif "city" in header:
                    prop["city"] = val
                elif "owner" in header:
                    prop["owner_name"] = val
                elif "assessed" in header:
                    prop["current_assessed_value_usd"] = _money(val)
                elif "market" in header or "just" in header:
                    prop["current_market_value_usd"] = _money(val)
                elif "tax" in header:
                    prop["current_tax_annual_usd"] = _money(val)
                elif "year" in header and "built" in header:
                    prop["year_built"] = _year(val)
                elif "sq" in header or "area" in header or "size" in header:
                    prop["sq_ft_living"] = _sqft(val) or _money(val)
                elif "type" in header or "use" in header:
                    prop["property_type"] = val

            if prop["parcel_number"] or prop["owner_name"]:
                parcels.append(prop)

    return parcels


# ---------------------------------------------------------------------------
# County handler registry
# ---------------------------------------------------------------------------

# Key: f"{county_snake}_{state_lower}"
# Value: async callable(crawler, query) -> list[dict]

_COUNTY_HANDLERS: dict[str, Any] = {
    "los_angeles_ca": _scrape_la_ca,
    "alameda_ca": _scrape_alameda_ca,
    "san_diego_ca": _scrape_san_diego_ca,
    "san_francisco_ca": _scrape_sf_ca,
    "orange_ca": _scrape_orange_ca,
    "riverside_ca": _scrape_riverside_ca,
    "miami_dade_fl": _scrape_miami_dade_fl,
    "broward_fl": _scrape_broward_fl,
    "palm_beach_fl": _scrape_palm_beach_fl,
    "hillsborough_fl": _scrape_hillsborough_fl,
    "pinellas_fl": _scrape_pinellas_fl,
    "new_york_ny": _scrape_nyc_ny,
    "kings_ny": _scrape_nyc_ny,
    "queens_ny": _scrape_nyc_ny,
    "bronx_ny": _scrape_nyc_ny,
    "richmond_ny": _scrape_nyc_ny,
    "cook_il": _scrape_cook_il,
    "maricopa_az": _scrape_maricopa_az,
    "clark_nv": _scrape_clark_nv,
    "king_wa": _scrape_king_wa,
    "fulton_ga": _scrape_fulton_ga,
    "dekalb_ga": _scrape_dekalb_ga,
    "mecklenburg_nc": _scrape_mecklenburg_nc,
    "denver_co": _scrape_denver_co,
    "arapahoe_co": _scrape_arapahoe_co,
}


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("county_assessor_multi")
class CountyAssessorMultiCrawler(HttpxCrawler):
    """
    Multi-state county assessor dispatcher. Routes to the correct
    county portal and parses property data with county-specific logic.

    identifier:
        "John Smith | Miami-Dade FL"
        "123 Main St | Cook County IL"
        "John Smith | Los Angeles CA"

    source_reliability: 0.90
    proxy_tier: datacenter
    """

    platform = "county_assessor_multi"
    source_reliability = 0.90
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query, county, state = _parse_identifier(identifier)

        if not state:
            return self._result(
                identifier,
                found=False,
                error="state_required — include state abbreviation in identifier",
            )

        county_key = _resolve_county_key(county, state)
        if not county_key:
            return self._result(
                identifier,
                found=False,
                error=f"no_handler_for_{county}_{state}",
            )

        handler = _COUNTY_HANDLERS.get(county_key)
        if not handler:
            return self._result(
                identifier,
                found=False,
                error=f"handler_not_implemented_{county_key}",
            )

        try:
            properties = await handler(self, query)
        except Exception as exc:
            logger.warning("CountyAssessorMulti handler error %s: %s", county_key, exc)
            return self._result(identifier, found=False, error=str(exc))

        found = len(properties) > 0

        return self._result(
            identifier,
            found=found,
            properties=properties,
            query=query,
            county_key=county_key,
        )
