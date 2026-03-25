"""
netronline_public.py — Netronline.com county assessor router.

Netronline.com aggregates links to all 3,000+ US county assessor and
recorder sites. This crawler:
  1. Resolves the correct county assessor URL for the given state/county
     via Netronline's search
  2. Navigates to that county's official public portal
  3. Scrapes parcel data: owner, assessed value, tax records

Because actual county portal structures vary enormously, this crawler
implements a routing table for the 50 largest counties and falls back
to a Netronline iframe extraction for others.

Registered as "netronline_public".

identifier formats:
    "John Smith | TX"
    "123 Main St | Dallas | TX"
    "John Smith | Harris County TX"
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

# ---------------------------------------------------------------------------
# Netronline search endpoint
# ---------------------------------------------------------------------------

_NETRONLINE_SEARCH = (
    "https://www.netronline.com/county_search.php"
    "?state={state}&county={county}"
)
_NETRONLINE_BASE = "https://www.netronline.com"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.netronline.com/",
}

# ---------------------------------------------------------------------------
# Known county assessor search endpoints
# Keyed by (state_abbr, county_name_lower) → URL template with {query}
# ---------------------------------------------------------------------------

_COUNTY_PORTALS: dict[tuple[str, str], str] = {
    # Texas
    ("tx", "harris"): "https://hcad.org/hcad-resources/hcad-online-databases/hcad-real-property/?account={query}",
    ("tx", "dallas"): "https://www.dallascad.org/SearchAddr.aspx?addr={query}",
    ("tx", "tarrant"): "https://www.tad.org/property-search/?search_type=address&query={query}",
    ("tx", "bexar"): "https://www.bcad.org/propertysearch/?PropertySearch={query}",
    ("tx", "travis"): "https://search.traviscad.org/results/?searchType=address&searchValue={query}",
    ("tx", "collin"): "https://www.collincad.org/propertysearch?AccountNumber={query}",
    ("tx", "denton"): "https://www.dentoncad.com/propertysearch?search={query}",
    # California
    ("ca", "los angeles"): "https://portal.assessor.lacounty.gov/parcelsearch/search?search={query}",
    ("ca", "alameda"): "https://www.acgov.org/ptax_pub_app/RealSearchInit.do?userAction=SEARCH&searchType=ADDR&searchAddr={query}",
    ("ca", "san diego"): "https://arcc.co.san-diego.ca.us/onlinesvc/SearchParcel.aspx?address={query}",
    ("ca", "orange"): "https://www.ocassessor.gov/asp/parcel.asp?address={query}",
    ("ca", "riverside"): "https://assessor.rivcoda.org/internetasmt/search?criteria.ownerName={query}",
    # Florida
    ("fl", "miami-dade"): "https://www.miamidade.gov/Apps/PA/propertysearch/Results.asp?address={query}",
    ("fl", "broward"): "https://www.bcpa.net/RecInfo.asp?URL_Folio=0000&URL_NAME=&URL_ADDR={query}",
    ("fl", "palm beach"): "https://www.pbcgov.org/papa/Asps/PropertyDetail/PropertyDetail.aspx?parcel={query}",
    ("fl", "hillsborough"): "https://gis.hcpafl.org/propertysearch/#/nav/search?searchText={query}",
    ("fl", "pinellas"): "https://www.pcpao.org/search_res.php?qval={query}&searchType=addr",
    # New York
    ("ny", "new york"): "https://a836-acris.nyc.gov/bblsearch/BBLSearch.aspx?parcel={query}",
    ("ny", "kings"): "https://a836-acris.nyc.gov/bblsearch/BBLSearch.aspx?parcel={query}",
    ("ny", "queens"): "https://a836-acris.nyc.gov/bblsearch/BBLSearch.aspx?parcel={query}",
    # Illinois
    ("il", "cook"): "https://www.cookcountyassessor.com/address-search?address={query}",
    # Arizona
    ("az", "maricopa"): "https://mcassessor.maricopa.gov/mcs.php?q={query}",
    # Nevada
    ("nv", "clark"): "https://www.clarkcountynv.gov/government/departments/assessor/property_search/index.php?search_str={query}",
    # Washington
    ("wa", "king"): "https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx?search_type=address&search_str={query}",
    # Georgia
    ("ga", "fulton"): "https://iaspublicaccess.fultoncountyga.gov/ias/Subscribers/FultonCountyGA/1/AccountDatalet.aspx?AccountNumber={query}",
    ("ga", "dekalb"): "https://www.qpublic.net/ga/dekalb/search.html?name={query}",
    # North Carolina
    ("nc", "mecklenburg"): "https://polaris3g.mecklenburgcountync.gov/search/parcelsearch?s={query}",
    # Colorado
    ("co", "denver"): "https://www.denvergov.org/assessor/assessor/main/assessorAddress.aspx?addr={query}",
    ("co", "arapahoe"): "https://www.arapahoegov.com/1297/Property-Search?search={query}",
}


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Returns (query, county, state).
    Handles:
        "John Smith | TX"
        "123 Main St | Dallas | TX"
        "John Smith | Harris County TX"
    """
    parts = [p.strip() for p in identifier.split("|")]
    query = parts[0]
    county = ""
    state = ""

    if len(parts) == 2:
        # Either "state" or "county state"
        loc = parts[1]
        # Check for "County" keyword
        m = re.match(r"(.+?)\s+County\s+([A-Z]{2})$", loc, re.I)
        if m:
            county = m.group(1).strip()
            state = m.group(2).strip().upper()
        elif re.match(r"^[A-Z]{2}$", loc.strip()):
            state = loc.strip().upper()
        else:
            # Assume last two chars are state if the string ends with a state abbr
            m2 = re.search(r"\b([A-Z]{2})$", loc.strip())
            if m2:
                state = m2.group(1)
                county = loc[: m2.start()].strip()

    elif len(parts) >= 3:
        # "query | city/county | state"
        county = parts[1]
        state = parts[2].strip().upper()
        # Remove "County" suffix if present
        county = re.sub(r"\s+County$", "", county, flags=re.I).strip()

    return query, county.lower(), state.upper()


# ---------------------------------------------------------------------------
# Generic Netronline portal lookup
# ---------------------------------------------------------------------------


def _extract_assessor_url_from_netronline(html: str) -> str | None:
    """Find the assessor/recorder link in a Netronline search results page."""
    soup = BeautifulSoup(html, "html.parser")
    # Look for table rows with "assessor" in the text
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = link.get_text(strip=True).lower()
        if "assessor" in text or "appraiser" in text or "property" in text:
            if href.startswith("http"):
                return href
            elif href.startswith("/"):
                return _NETRONLINE_BASE + href
    return None


# ---------------------------------------------------------------------------
# Generic county portal scraper
# ---------------------------------------------------------------------------


def _parse_generic_assessor_html(html: str, query: str) -> dict[str, Any]:
    """
    Generic parser for county assessor result pages.
    Extracts owner, parcel, assessed value, address from common HTML structures.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        "parcel_number": None,
        "street_address": None,
        "city": None,
        "state": None,
        "zip_code": None,
        "owner_name": None,
        "current_assessed_value_usd": None,
        "current_market_value_usd": None,
        "current_tax_annual_usd": None,
        "year_built": None,
        "sq_ft_living": None,
        "property_type": None,
    }

    text = soup.get_text(" ", strip=True)

    # Parcel / APN
    m = re.search(r"(?:parcel|apn|account)[:\s#]*([0-9\-]{8,20})", text, re.I)
    if m:
        result["parcel_number"] = m.group(1).strip()

    # Owner name — look for "Owner:" label pattern
    m = re.search(r"Owner[:\s]+([A-Z][A-Z\s,\.&']{3,50}?)(?:\s{2,}|$|\n)", text, re.I)
    if m:
        result["owner_name"] = m.group(1).strip()

    # Assessed value
    m = re.search(r"(?:assessed|appraised)[^$\d]*\$?([\d,]{4,12})", text, re.I)
    if m:
        try:
            result["current_assessed_value_usd"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Market / just value
    m = re.search(r"(?:market|just)\s*value[^$\d]*\$?([\d,]{4,12})", text, re.I)
    if m:
        try:
            result["current_market_value_usd"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Tax
    m = re.search(r"(?:tax|taxes)[^$\d]*\$?([\d,]{3,10})", text, re.I)
    if m:
        try:
            result["current_tax_annual_usd"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Year built
    m = re.search(r"(?:year built|built in)[:\s]+(\d{4})", text, re.I)
    if m:
        result["year_built"] = int(m.group(1))

    # Sq ft
    m = re.search(r"(?:sq\.?\s*ft|square\s*feet)[:\s]+([\d,]+)", text, re.I)
    if m:
        try:
            result["sq_ft_living"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return result


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("netronline_public")
class NetronlinePublicCrawler(HttpxCrawler):
    """
    Routes to official county assessor sites via Netronline.com.
    Covers all US counties — uses a direct routing table for the 30
    largest and falls back to Netronline iframe discovery for others.

    identifier:
        "John Smith | TX"
        "123 Main St | Dallas | TX"
        "John Smith | Harris County TX"

    source_reliability: 0.88
    proxy_tier: datacenter
    """

    platform = "netronline_public"
    source_reliability = 0.88
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query, county, state = _parse_identifier(identifier)

        if not state:
            return self._result(
                identifier,
                found=False,
                error="state_required — include state abbr in identifier",
            )

        # Look up in routing table
        portal_url_template = _COUNTY_PORTALS.get((state.lower(), county))
        if not portal_url_template and county:
            # Try first word of county (e.g. "harris" from "harris county")
            portal_url_template = _COUNTY_PORTALS.get((state.lower(), county.split()[0]))

        if portal_url_template:
            assessor_url = portal_url_template.format(query=quote_plus(query))
        else:
            # Fall back to Netronline lookup
            assessor_url = await self._resolve_via_netronline(state, county)
            if assessor_url:
                # Append query param generically
                sep = "&" if "?" in assessor_url else "?"
                assessor_url = f"{assessor_url}{sep}q={quote_plus(query)}"

        if not assessor_url:
            return self._result(
                identifier,
                found=False,
                error=f"no_portal_found_for_{state}_{county}",
            )

        resp = await self.get(assessor_url, headers=_BROWSER_HEADERS)
        if resp is None or resp.status_code not in (200, 206):
            return self._result(
                identifier,
                found=False,
                error=f"portal_http_{resp.status_code if resp else 'timeout'}",
            )

        prop = _parse_generic_assessor_html(resp.text, query)
        prop["source_portal"] = assessor_url
        prop["county"] = county.title() if county else None
        prop["state"] = state
        prop["country"] = "US"

        found = any(v for k, v in prop.items() if k not in ("county", "state", "country", "source_portal"))

        return self._result(
            identifier,
            found=found,
            properties=[prop],
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_via_netronline(self, state: str, county: str) -> str | None:
        """Use Netronline to find the official assessor URL for a given county."""
        url = _NETRONLINE_SEARCH.format(
            state=state.lower(),
            county=quote_plus(county) if county else "",
        )
        try:
            resp = await self.get(url, headers=_BROWSER_HEADERS)
            if resp and resp.status_code == 200:
                return _extract_assessor_url_from_netronline(resp.text)
        except Exception as exc:
            logger.warning("Netronline lookup error: %s", exc)
        return None
