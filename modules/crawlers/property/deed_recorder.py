"""
deed_recorder.py — County clerk/recorder deed database crawler.

Searches official grantor/grantee indexes for deed transfers across
major US counties. Extracts:
    - Warranty deeds, quitclaim deeds, grant deeds
    - Instrument numbers, recording dates, consideration amounts
    - Grantor / grantee names
    - Deed of trust / mortgage instruments

Covers:
    LA County (CA)     — lavote.gov / acris
    Cook County (IL)   — cookcountyrecorder.com
    Harris County (TX) — hccountyclerk.com
    Maricopa (AZ)      — recorder.maricopa.gov
    Miami-Dade (FL)    — mdc.clerkmiamidade.gov
    Broward (FL)       — browardclerk.org
    King County (WA)   — kingcounty.gov/recorder
    Clark County (NV)  — clarkcountynv.gov/recorder
    NYC (ACRIS)        — acris.nyc.gov
    Fulton County (GA) — itsmynd.com (Fulton)

Registered as "deed_recorder".

identifier formats:
    "John Smith TX"
    "Smith, John | Harris County TX"
    "John Smith | Cook County IL"
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
# County recorder endpoint registry
# ---------------------------------------------------------------------------

# Each entry: county_key → {
#   "grantor_url": template with {name} for grantor search
#   "grantee_url": template with {name} for grantee search
#   "parser": function name string (resolved at runtime)
# }

_RECORDERS: dict[str, dict[str, Any]] = {
    "harris_tx": {
        "grantor_url": "https://www.cclerk.hctx.net/applications/websearch/RP.aspx?Name={name}&SearchType=Grantor",
        "grantee_url": "https://www.cclerk.hctx.net/applications/websearch/RP.aspx?Name={name}&SearchType=Grantee",
        "state": "TX",
    },
    "dallas_tx": {
        "grantor_url": "https://countyclerk.dallascounty.org/real-property/index-search/?name={name}&type=grantor",
        "grantee_url": "https://countyclerk.dallascounty.org/real-property/index-search/?name={name}&type=grantee",
        "state": "TX",
    },
    "cook_il": {
        "grantor_url": "https://www.cookcountyrecorder.com/grantor?name={name}",
        "grantee_url": "https://www.cookcountyrecorder.com/grantee?name={name}",
        "state": "IL",
    },
    "maricopa_az": {
        "grantor_url": "https://recorder.maricopa.gov/recdocdata/GetImgRecDocData.aspx?Grantor={name}",
        "grantee_url": "https://recorder.maricopa.gov/recdocdata/GetImgRecDocData.aspx?Grantee={name}",
        "state": "AZ",
    },
    "miami_dade_fl": {
        "grantor_url": "https://www2.miami-dadeclerk.com/public-records/search.aspx?QS=y&grantor={name}",
        "grantee_url": "https://www2.miami-dadeclerk.com/public-records/search.aspx?QS=y&grantee={name}",
        "state": "FL",
    },
    "broward_fl": {
        "grantor_url": "https://officialrecords.broward.org/AcclaimWeb/search/SearchTypeDocType?DocType=DEED&Name={name}&NameType=G",
        "grantee_url": "https://officialrecords.broward.org/AcclaimWeb/search/SearchTypeDocType?DocType=DEED&Name={name}&NameType=E",
        "state": "FL",
    },
    "king_wa": {
        "grantor_url": "https://recordsearch.kingcounty.gov/LandmarkWeb/search/index?theme=.blue&section=searchCriteriaName&quickSearchSelection=&grantor={name}",
        "grantee_url": "https://recordsearch.kingcounty.gov/LandmarkWeb/search/index?theme=.blue&section=searchCriteriaName&quickSearchSelection=&grantee={name}",
        "state": "WA",
    },
    "clark_nv": {
        "grantor_url": "https://www.clarkcountynv.gov/government/assessor/records/property_search/index.php?search_str={name}&type=owner",
        "grantee_url": "https://www.clarkcountynv.gov/government/assessor/records/property_search/index.php?search_str={name}&type=owner",
        "state": "NV",
    },
    "nyc_ny": {
        "grantor_url": "https://a836-acris.nyc.gov/DS/DocumentSearch/PartyName?housenum=&lastname={name}&firstname=&doctype=DEED&partytype=1",
        "grantee_url": "https://a836-acris.nyc.gov/DS/DocumentSearch/PartyName?housenum=&lastname={name}&firstname=&doctype=DEED&partytype=2",
        "state": "NY",
    },
    "los_angeles_ca": {
        "grantor_url": "https://rrcc.lacounty.gov/index.cfm?tm=grantor&q={name}",
        "grantee_url": "https://rrcc.lacounty.gov/index.cfm?tm=grantee&q={name}",
        "state": "CA",
    },
    "fulton_ga": {
        "grantor_url": "https://www.fultoncountyclerk.org/gruntee?name={name}&type=grantor",
        "grantee_url": "https://www.fultoncountyclerk.org/gruntee?name={name}&type=grantee",
        "state": "GA",
    },
}

# State → default county key (used when only state is given)
_STATE_DEFAULT: dict[str, str] = {
    "TX": "harris_tx",
    "IL": "cook_il",
    "AZ": "maricopa_az",
    "FL": "miami_dade_fl",
    "NV": "clark_nv",
    "WA": "king_wa",
    "NY": "nyc_ny",
    "CA": "los_angeles_ca",
    "GA": "fulton_ga",
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Deed type normalisation
_DEED_TYPES = {
    "wd": "Warranty Deed",
    "warranty": "Warranty Deed",
    "qcd": "Quitclaim Deed",
    "quitclaim": "Quitclaim Deed",
    "gd": "Grant Deed",
    "grant": "Grant Deed",
    "td": "Deed of Trust",
    "dot": "Deed of Trust",
    "deed of trust": "Deed of Trust",
    "foreclosure": "Foreclosure Deed",
    "trustee": "Trustee's Deed",
}


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Returns (name, county_key, state).
    Handles:
        "John Smith TX"
        "Smith, John | Harris County TX"
        "John Smith | Cook County IL"
    """
    if "|" in identifier:
        parts = [p.strip() for p in identifier.split("|", 1)]
        name = parts[0]
        loc = parts[1]
    else:
        # Try to split name from trailing state abbr
        m = re.match(r"^(.+?)\s+([A-Z]{2})$", identifier.strip())
        if m:
            name = m.group(1).strip()
            loc = m.group(2)
        else:
            return identifier.strip(), "", ""

    # Parse loc: "Harris County TX" or "Cook County IL" or just "TX"
    m2 = re.match(r"^([A-Za-z\s]+?)\s+County\s+([A-Z]{2})$", loc.strip(), re.I)
    if m2:
        county_name = m2.group(1).strip().lower().replace(" ", "_")
        state = m2.group(2).upper()
        # Build county key
        county_key = f"{county_name}_{state.lower()}"
        return name, county_key, state

    # Just state abbreviation
    m3 = re.match(r"^([A-Z]{2})$", loc.strip())
    if m3:
        state = m3.group(1).upper()
        return name, _STATE_DEFAULT.get(state, ""), state

    return name, "", ""


def _normalise_deed_type(raw: str) -> str:
    raw_lower = raw.lower().strip()
    for key, val in _DEED_TYPES.items():
        if key in raw_lower:
            return val
    return raw.strip()


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------


def _parse_deed_table(html: str, grantor_or_grantee: str) -> list[dict[str, Any]]:
    """
    Generic parser for tabular deed index results.
    Handles Harris County, Cook County, ACRIS, and similar patterns.
    """
    soup = BeautifulSoup(html, "html.parser")
    deeds: list[dict[str, Any]] = []

    # --- ACRIS (NYC) specific: data rows in a table with class "docSearchResults" ---
    acris_table = soup.find("table", {"id": re.compile(r"docSearch|search_results", re.I)})
    if acris_table:
        for row in acris_table.find_all("tr")[1:25]:  # skip header
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) >= 5:
                deeds.append(
                    {
                        "document_number": cells[0],
                        "acquisition_type": _normalise_deed_type(cells[1]),
                        "acquisition_date": cells[2],
                        "grantor": cells[3] if grantor_or_grantee == "grantee" else grantor_or_grantee,
                        "grantee": cells[4] if grantor_or_grantee == "grantor" else grantor_or_grantee,
                        "acquisition_price_usd": None,
                        "loan_amount_usd": None,
                        "owner_name": cells[4] if grantor_or_grantee == "grantor" else cells[3],
                        "owner_type": None,
                        "disposition_date": None,
                    }
                )
        if deeds:
            return deeds

    # --- Generic table with at least 4 columns ---
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not any(k in " ".join(headers) for k in ("grantor", "grantee", "document", "deed", "instrument")):
            continue
        for row in rows[1:30]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            deed: dict[str, Any] = {
                "document_number": None,
                "acquisition_type": None,
                "acquisition_date": None,
                "grantor": None,
                "grantee": None,
                "acquisition_price_usd": None,
                "loan_amount_usd": None,
                "owner_name": None,
                "owner_type": None,
                "disposition_date": None,
            }
            for i, header in enumerate(headers):
                if i >= len(cells):
                    break
                val = cells[i]
                if "instrument" in header or "doc" in header:
                    deed["document_number"] = val
                elif "type" in header or "deed" in header:
                    deed["acquisition_type"] = _normalise_deed_type(val)
                elif "date" in header and "record" in header:
                    deed["acquisition_date"] = val
                elif "grantor" in header:
                    deed["grantor"] = val
                elif "grantee" in header:
                    deed["grantee"] = val
                elif "amount" in header or "consider" in header:
                    m = re.search(r"[\d,]+", val.replace("$", ""))
                    if m:
                        try:
                            deed["acquisition_price_usd"] = int(m.group().replace(",", ""))
                        except ValueError:
                            pass

            deed["owner_name"] = deed["grantee"] if grantor_or_grantee == "grantor" else deed["grantor"]
            if deed["document_number"] or deed["grantor"]:
                deeds.append(deed)

    return deeds


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("deed_recorder")
class DeedRecorderCrawler(HttpxCrawler):
    """
    Searches official county clerk/recorder grantor-grantee deed indexes.

    identifier:
        "John Smith TX"
        "Smith, John | Harris County TX"
        "John Smith | Cook County IL"

    Returns ownership_history list with full deed transfer details.
    source_reliability: 0.92
    proxy_tier: datacenter
    """

    platform = "deed_recorder"
    source_reliability = 0.92
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        name, county_key, state = _parse_identifier(identifier)

        if not name:
            return self._result(identifier, found=False, error="name_required")

        # Resolve recorder config
        recorder = _RECORDERS.get(county_key)
        if not recorder and state:
            default_key = _STATE_DEFAULT.get(state.upper())
            recorder = _RECORDERS.get(default_key or "")

        if not recorder:
            return self._result(
                identifier,
                found=False,
                error=f"no_recorder_for_{county_key or state}",
            )

        encoded_name = quote_plus(name)
        all_deeds: list[dict[str, Any]] = []

        # Fetch as grantor (seller)
        grantor_url = recorder["grantor_url"].format(name=encoded_name)
        grantor_resp = await self.get(grantor_url, headers=_BROWSER_HEADERS)
        if grantor_resp and grantor_resp.status_code == 200:
            deeds = _parse_deed_table(grantor_resp.text, name)
            all_deeds.extend(deeds)

        # Fetch as grantee (buyer)
        grantee_url = recorder["grantee_url"].format(name=encoded_name)
        grantee_resp = await self.get(grantee_url, headers=_BROWSER_HEADERS)
        if grantee_resp and grantee_resp.status_code == 200:
            deeds = _parse_deed_table(grantee_resp.text, name)
            # Merge, deduplicating by document_number
            seen = {d.get("document_number") for d in all_deeds if d.get("document_number")}
            for d in deeds:
                if d.get("document_number") not in seen:
                    all_deeds.append(d)

        found = len(all_deeds) > 0

        return self._result(
            identifier,
            found=found,
            ownership_history=all_deeds,
            total_deeds=len(all_deeds),
            name_searched=name,
            county=county_key,
            state=state,
            grantor_url=grantor_url,
            grantee_url=grantee_url,
        )
