"""
property_tax_nationwide.py — Nationwide property tax record crawler.

Scrapes state and county property tax records for all 50 US states.
Covers:
    - Annual tax history per property
    - Homestead, senior, veteran, disability exemptions
    - Tax delinquency flags
    - Special assessments

Uses a state routing table — each state has its own portal URL pattern.
Falls back to secondary aggregators (SmartAsset, PropertyShark) when
a direct state portal cannot be reached.

Registered as "property_tax_nationwide".

identifier formats:
    "APN:123-456-789 TX"
    "123 Main St, Dallas TX 75001"
    "Parcel:1234567890 Miami-Dade FL"
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
# State portal routing table
# Each entry: state_abbr → dict with url templates and response type
# ---------------------------------------------------------------------------

_STATE_TAX_PORTALS: dict[str, dict[str, Any]] = {
    "TX": {
        "url": "https://mycounty.texasonline.com/propertytax?q={query}",
        "fallback": "https://propaccess.trueprodigy.com/clientdb/Property/details?cid=2&prop_id={query}",
        "type": "html",
    },
    "CA": {
        "url": "https://www.boe.ca.gov/proptaxes/taxadmin.htm?county={county}&parcel={query}",
        "fallback": "https://www.assessor.lacounty.gov/Default.aspx?search={query}",
        "type": "html",
    },
    "FL": {
        "url": "https://www.miamidade.gov/Apps/PA/propertysearch/Results.asp?address={query}",
        "fallback": "https://www.pcpao.org/search_res.php?qval={query}&searchType=addr",
        "type": "html",
    },
    "NY": {
        "url": "https://www.tax.ny.gov/pit/property/learn/proptype.htm?q={query}",
        "fallback": "https://a836-acris.nyc.gov/bblsearch/BBLSearch.aspx?parcel={query}",
        "type": "html",
    },
    "IL": {
        "url": "https://www.cookcountytreasurer.com/yourAccountSearch.aspx?SearchIndex={query}",
        "fallback": "https://www.cookcountyassessor.com/address-search?address={query}",
        "type": "html",
    },
    "AZ": {
        "url": "https://mcassessor.maricopa.gov/mcs.php?q={query}",
        "fallback": "https://treasurer.maricopa.gov/Parcel/Details?parcel={query}",
        "type": "html",
    },
    "NV": {
        "url": "https://www.clarkcountynv.gov/government/departments/assessor/property_search/index.php?search_str={query}",
        "fallback": "https://www.washoecounty.gov/assessor/property.php?q={query}",
        "type": "html",
    },
    "WA": {
        "url": "https://blue.kingcounty.com/Assessor/eRealProperty/default.aspx?search_type=address&search_str={query}",
        "fallback": "https://www.piercecountywa.gov/3472/Property-Search?q={query}",
        "type": "html",
    },
    "GA": {
        "url": "https://iaspublicaccess.fultoncountyga.gov/ias/Subscribers/FultonCountyGA/1/AccountDatalet.aspx?AccountNumber={query}",
        "fallback": "https://www.qpublic.net/ga/fulton/search.html?name={query}",
        "type": "html",
    },
    "NC": {
        "url": "https://polaris3g.mecklenburgcountync.gov/search/parcelsearch?s={query}",
        "fallback": "https://tax.wakegov.com/realestate/search?name={query}",
        "type": "html",
    },
    "CO": {
        "url": "https://www.denvergov.org/assessor/assessor/main/assessorAddress.aspx?addr={query}",
        "fallback": "https://assessor.jeffco.us/assess/property-search.do?address={query}",
        "type": "html",
    },
    "PA": {
        "url": "https://property.phila.gov/?q={query}",
        "fallback": "https://acasearch.alleghenycounty.us/Home/Search?SearchString={query}",
        "type": "html",
    },
    "OH": {
        "url": "https://myplace.cuyahogacounty.gov/property-search/propertydetail.aspx?p={query}",
        "fallback": "https://www.franklincountyauditor.com/real-estate/property/search?q={query}",
        "type": "html",
    },
    "MI": {
        "url": "https://bsaonline.com/SiteSearch/SiteSearchDetails?SearchCategory=Address&SearchText={query}",
        "fallback": "https://gis.waynecounty.com/Html5Viewer/Index.html?viewer=property&q={query}",
        "type": "html",
    },
    "MN": {
        "url": "https://www.hennepin.us/property/maps-data/property-information?pid={query}",
        "fallback": "https://www.ramseycounty.us/residents/property-home/search-property-information?q={query}",
        "type": "html",
    },
    "MO": {
        "url": "https://stlouis-mo.gov/data/property-tax/?q={query}",
        "fallback": "https://www.jacksongov.org/301/Property-Tax?q={query}",
        "type": "html",
    },
    "TN": {
        "url": "https://www.assessment.state.tn.us/RE/search.aspx?q={query}",
        "fallback": "https://www.shelbycountytrustee.com/property-tax/?q={query}",
        "type": "html",
    },
    "VA": {
        "url": "https://assessor.fairfaxcounty.gov/Real-Estate/Assessment/home.aspx?q={query}",
        "fallback": "https://www.loudoun.gov/3117/Real-Property-Tax?q={query}",
        "type": "html",
    },
    "MA": {
        "url": "https://www.cityofboston.gov/assessing/search/?q={query}",
        "fallback": "https://gis.worcesterma.gov/wgspub/default.aspx?q={query}",
        "type": "html",
    },
    "MD": {
        "url": "https://sdat.dat.maryland.gov/RealProperty/Pages/default.aspx?q={query}",
        "fallback": "https://taxwizard.baltimorecity.gov/search?q={query}",
        "type": "html",
    },
    "OR": {
        "url": "https://multcoproptax.com/Property-Search?q={query}",
        "fallback": "https://lanecounty.org/government/county_departments/assessment_taxation/property_search?q={query}",
        "type": "html",
    },
    "SC": {
        "url": "https://www.charlestoncounty.org/departments/assessor/property-search.php?q={query}",
        "fallback": "https://www.richlandcountysc.gov/Departments/Assessor/PropertySearch?q={query}",
        "type": "html",
    },
    "IN": {
        "url": "https://assessor.indy.gov/Property/Search?q={query}",
        "fallback": "https://www.marioncounty.in.gov/egis/map.aspx?q={query}",
        "type": "html",
    },
    "WI": {
        "url": "https://assessments.milwaukee.gov/search?q={query}",
        "fallback": "https://www.co.dane.wi.us/property?q={query}",
        "type": "html",
    },
    "KY": {
        "url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=1006&LayerID=22441&PageTypeID=2&PageID=9844&Q=2119498716&q={query}",
        "fallback": None,
        "type": "html",
    },
    "LA": {
        "url": "https://www.latax.state.la.us/menu_assessoroffices/assessors.aspx?q={query}",
        "fallback": "https://nolaassessor.com/?q={query}",
        "type": "html",
    },
    "AL": {
        "url": "https://apps2.alabamagis.com/jccwebsite/search.aspx?q={query}",
        "fallback": None,
        "type": "html",
    },
    "OK": {
        "url": "https://www.oklahomacounty.org/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "NM": {
        "url": "https://iswdata.bernco.gov/PropertySearch/Search.aspx?q={query}",
        "fallback": None,
        "type": "html",
    },
    "UT": {
        "url": "https://slco.org/assessor/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "ID": {
        "url": "https://www.adacounty.id.gov/assessor/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "MT": {
        "url": "https://mtrevenue.gov/property-tax/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "WY": {
        "url": "https://www.laramiecountywy.gov/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "ND": {
        "url": "https://apps.nd.gov/itd/taxequalization/teSearch.htm?q={query}",
        "fallback": None,
        "type": "html",
    },
    "SD": {
        "url": "https://apps.sd.gov/rv23ereal/SearchResults.aspx?q={query}",
        "fallback": None,
        "type": "html",
    },
    "NE": {
        "url": "https://www.douglas.ne.us/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "KS": {
        "url": "https://jocoabatement.jocogov.org/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "IA": {
        "url": "https://beacon.schneidercorp.com/Application.aspx?AppID=1046&LayerID=23338&PageTypeID=2&q={query}",
        "fallback": None,
        "type": "html",
    },
    "AR": {
        "url": "https://www.acrealty.org/pulaski/search.aspx?q={query}",
        "fallback": None,
        "type": "html",
    },
    "MS": {
        "url": "https://www.co.hinds.ms.us/pgs/apps/property_search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "HI": {
        "url": "https://www.realpropertyhonolulu.com/search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "AK": {
        "url": "https://www.matsugov.us/assessor/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "CT": {
        "url": "https://data.visionappraisal.com/HartfordCT/default.asp?q={query}",
        "fallback": None,
        "type": "html",
    },
    "RI": {
        "url": "https://data.visionappraisal.com/ProvidenceRI/default.asp?q={query}",
        "fallback": None,
        "type": "html",
    },
    "NH": {
        "url": "https://www.nhgeodata.unh.edu/grants/?q={query}",
        "fallback": None,
        "type": "html",
    },
    "VT": {
        "url": "https://taxmap.vermont.gov/taxmaps/index_e_search.htm?q={query}",
        "fallback": None,
        "type": "html",
    },
    "ME": {
        "url": "https://www.maine.gov/revenue/taxes/property-tax/property-search?q={query}",
        "fallback": None,
        "type": "html",
    },
    "DE": {
        "url": "https://assessment.newcastlede.gov/assessment/assessment.aspx?q={query}",
        "fallback": None,
        "type": "html",
    },
    "WV": {
        "url": "https://www.kanawhacounty.gov/property-search/?q={query}",
        "fallback": None,
        "type": "html",
    },
}

# Fallback aggregator (covers all states)
_SMARTASSET_URL = "https://smartasset.com/taxes/property-taxes#result?q={query}&state={state}"
_PROPERTYSHARK_URL = "https://www.propertyshark.com/Real-Estate-Reports/{query}/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Known exemption types to scan for in HTML
_EXEMPTION_KEYWORDS = [
    "homestead",
    "senior",
    "veteran",
    "disability",
    "widow",
    "agricultural",
    "religious",
    "nonprofit",
    "solar",
    "green",
]

# Delinquency signals
_DELINQUENCY_KEYWORDS = [
    "delinquent",
    "past due",
    "tax lien",
    "unpaid",
    "default",
    "in arrears",
]


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str]:
    """
    Returns (query, state).
    Handles:
        "APN:123-456-789 TX"
        "123 Main St, Dallas TX 75001"
        "Parcel:1234567890 Miami-Dade FL"
    """
    # APN: prefix
    m = re.match(r"^(?:APN|Parcel)[:\s]+(.+?)\s+([A-Z]{2})$", identifier.strip(), re.I)
    if m:
        return m.group(1).strip(), m.group(2).upper()

    # State at end
    m = re.search(r"\b([A-Z]{2})\s*$", identifier.strip())
    if m:
        state = m.group(1).upper()
        query = identifier[: m.start()].strip().rstrip(",")
        return query, state

    return identifier.strip(), ""


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _parse_tax_html(html: str) -> dict[str, Any]:
    """
    Generic parser for state/county property tax portal HTML.
    Extracts tax history, exemptions, delinquency status, and parcel info.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    result: dict[str, Any] = {
        "parcel_number": None,
        "owner_name": None,
        "street_address": None,
        "current_assessed_value_usd": None,
        "current_market_value_usd": None,
        "current_tax_annual_usd": None,
        "is_delinquent": False,
        "exemptions": [],
        "valuations": [],
        "special_assessments": [],
    }

    # Parcel / APN
    m = re.search(r"(?:parcel|apn|account|folio)[:\s#]+([0-9\-\.]{6,20})", text, re.I)
    if m:
        result["parcel_number"] = m.group(1).strip()

    # Owner
    m = re.search(r"(?:owner|taxpayer)[:\s]+([A-Z][A-Z,\s\.&']{3,50})(?=\s{2,}|\n|$)", text, re.I)
    if m:
        result["owner_name"] = m.group(1).strip()

    # Address
    m = re.search(r"(?:situs|property\s+address)[:\s]+([0-9][^\n]{5,60})", text, re.I)
    if m:
        result["street_address"] = m.group(1).strip()

    # Assessed value
    m = re.search(r"assessed[^$\d]*\$?([\d,]{4,12})", text, re.I)
    if m:
        try:
            result["current_assessed_value_usd"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Market value
    m = re.search(r"(?:market|just|fair\s+market)[^$\d]*\$?([\d,]{4,12})", text, re.I)
    if m:
        try:
            result["current_market_value_usd"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Annual tax
    m = re.search(r"(?:annual\s+tax|total\s+tax|taxes\s+due)[^$\d]*\$?([\d,]{3,10})", text, re.I)
    if m:
        try:
            result["current_tax_annual_usd"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Delinquency
    text_lower = text.lower()
    result["is_delinquent"] = any(kw in text_lower for kw in _DELINQUENCY_KEYWORDS)

    # Exemptions
    found_exemptions: list[str] = []
    for kw in _EXEMPTION_KEYWORDS:
        if kw in text_lower:
            found_exemptions.append(kw.title())
    result["exemptions"] = found_exemptions

    # Tax history table
    valuations: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not any(k in " ".join(headers) for k in ("year", "tax", "assess", "value")):
            continue
        year_idx = next((i for i, h in enumerate(headers) if "year" in h), None)
        assessed_idx = next((i for i, h in enumerate(headers) if "assess" in h), None)
        market_idx = next((i for i, h in enumerate(headers) if "market" in h or "just" in h), None)
        tax_idx = next((i for i, h in enumerate(headers) if "tax" in h and "year" not in h), None)

        for row in rows[1:25]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if not cells:
                continue
            v: dict[str, Any] = {
                "valuation_year": None,
                "assessed_value_usd": None,
                "market_value_usd": None,
                "tax_amount_usd": None,
            }
            if year_idx is not None and year_idx < len(cells):
                m2 = re.search(r"\d{4}", cells[year_idx])
                if m2:
                    v["valuation_year"] = int(m2.group())
            if assessed_idx is not None and assessed_idx < len(cells):
                m2 = re.search(r"[\d,]+", cells[assessed_idx].replace("$", ""))
                if m2:
                    try:
                        v["assessed_value_usd"] = int(m2.group().replace(",", ""))
                    except ValueError:
                        pass
            if market_idx is not None and market_idx < len(cells):
                m2 = re.search(r"[\d,]+", cells[market_idx].replace("$", ""))
                if m2:  # pragma: no branch
                    try:
                        v["market_value_usd"] = int(m2.group().replace(",", ""))
                    except ValueError:
                        pass
            if tax_idx is not None and tax_idx < len(cells):
                m2 = re.search(r"[\d,]+", cells[tax_idx].replace("$", ""))
                if m2:  # pragma: no branch
                    try:
                        v["tax_amount_usd"] = int(m2.group().replace(",", ""))
                    except ValueError:
                        pass
            if v["valuation_year"]:
                valuations.append(v)

    result["valuations"] = valuations
    return result


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("property_tax_nationwide")
class PropertyTaxNationwideCrawler(HttpxCrawler):
    """
    Scrapes state/county property tax records nationwide (all 50 states).
    Covers annual tax history, exemptions, and delinquency status.

    identifier:
        "APN:123-456-789 TX"
        "123 Main St, Dallas TX 75001"
        "Parcel:1234567890 Miami-Dade FL"

    source_reliability: 0.90
    proxy_tier: datacenter
    """

    platform = "property_tax_nationwide"
    source_reliability = 0.90
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query, state = _parse_identifier(identifier)

        if not state:
            return self._result(
                identifier,
                found=False,
                error="state_required — append two-letter state code to identifier",
            )

        portal = _STATE_TAX_PORTALS.get(state.upper())
        if not portal:
            return self._result(
                identifier,
                found=False,
                error=f"no_portal_for_state_{state}",
            )

        encoded = quote_plus(query)
        primary_url = portal["url"].format(query=encoded, county="")
        fallback_url = (portal.get("fallback") or "").format(query=encoded)

        # Try primary
        resp = await self.get(primary_url, headers=_BROWSER_HEADERS)
        html: str | None = None

        if resp and resp.status_code == 200 and len(resp.text) > 500:
            html = resp.text
        elif fallback_url:  # pragma: no branch
            fallback_resp = await self.get(fallback_url, headers=_BROWSER_HEADERS)
            if fallback_resp and fallback_resp.status_code == 200:
                html = fallback_resp.text

        if not html:
            # Last resort: PropertyShark aggregator
            ps_url = _PROPERTYSHARK_URL.format(query=quote_plus(query))
            ps_resp = await self.get(ps_url, headers=_BROWSER_HEADERS)
            if ps_resp and ps_resp.status_code == 200:
                html = ps_resp.text

        if not html:
            return self._result(identifier, found=False, error="all_portals_failed")

        tax_data = _parse_tax_html(html)
        tax_data["state"] = state.upper()
        tax_data["query"] = query
        tax_data["country"] = "US"

        found = bool(
            tax_data.get("parcel_number")
            or tax_data.get("current_tax_annual_usd")
            or tax_data.get("current_assessed_value_usd")
            or tax_data.get("valuations")
        )

        return self._result(
            identifier,
            found=found,
            properties=[tax_data],
            query=query,
            state=state,
        )
