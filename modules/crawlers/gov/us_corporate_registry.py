"""
us_corporate_registry.py — US corporate registry officer/director search.

Aggregates corporate officer and director records from:
1. OpenCorporates API officer search (global, includes all US states)
2. Direct state portal scraping for DE, WY, NV, FL, TX, CA, NY where
   OpenCorporates coverage may be incomplete.

Registered as "us_corporate_registry".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_OC_OFFICER_SEARCH = (
    "https://api.opencorporates.com/v0.4/officers/search"
    "?q={query}&jurisdiction_code={jur}&format=json&per_page=50"
)
_OC_OFFICER_ALL = (
    "https://api.opencorporates.com/v0.4/officers/search?q={query}&format=json&per_page=100"
)

# Key state portal search endpoints (public, no auth needed for basic search)
_STATE_PORTALS: dict[str, str] = {
    "de": "https://icis.corp.delaware.gov/ecorp/entitysearch/namesearch.aspx",
    "fl": "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults/EntityName/{query}/Page1",
    "wy": "https://wyobiz.wyo.gov/Business/FilingSearch.aspx",
    "nv": "https://esos.nv.gov/EntitySearch/OnlineEntitySearch",
    "tx": "https://mycpa.cpa.state.tx.us/coa/Index.do",
    "ca": "https://bizfileonline.sos.ca.gov/search/business",
    "ny": "https://apps.dos.ny.gov/publicInquiry/EntitySearch",
}

_US_STATE_JURISDICTIONS = [
    "us_de",
    "us_fl",
    "us_wy",
    "us_nv",
    "us_tx",
    "us_ca",
    "us_ny",
    "us_il",
    "us_wa",
    "us_co",
    "us_ga",
    "us_nc",
]


def _parse_oc_officers(data: dict) -> list[dict[str, Any]]:
    """Parse OpenCorporates officer search response into normalised records."""
    roles: list[dict[str, Any]] = []
    results = data.get("results", {})
    for item in results.get("officers", []):
        officer = item.get("officer", item)
        company = officer.get("company", {}) or {}
        roles.append(
            {
                "company_name": company.get("name", ""),
                "company_number": company.get("company_number", ""),
                "jurisdiction": company.get("jurisdiction_code", ""),
                "role": officer.get("position", ""),
                "appointment_date": officer.get("start_date", ""),
                "resignation_date": officer.get("end_date", ""),
                "is_current": not bool(officer.get("end_date")),
                "company_status": company.get("current_status", ""),
                "registered_address": (
                    company.get("registered_address", {}).get("in_full", "")
                    if isinstance(company.get("registered_address"), dict)
                    else str(company.get("registered_address", ""))
                ),
                "source": "opencorporates",
            }
        )
    return roles


def _parse_florida_html(html: str, query: str) -> list[dict[str, Any]]:
    """
    Parse Florida Sunbiz search results.
    Sunbiz returns a simple table with entity name, document number, status.
    """
    roles: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # Results table has class 'search-results'
        table = soup.find("table", class_="search-results") or soup.find("table")
        if not table:
            return roles
        rows = table.find_all("tr")
        if len(rows) < 2:
            return roles
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            entity_name = cells[0].get_text(strip=True)
            doc_number = cells[1].get_text(strip=True)
            status = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            if not entity_name:
                continue
            roles.append(
                {
                    "company_name": entity_name,
                    "company_number": doc_number,
                    "jurisdiction": "us_fl",
                    "role": "officer/registered agent",
                    "appointment_date": "",
                    "resignation_date": "",
                    "is_current": "active" in status.lower(),
                    "company_status": status,
                    "registered_address": "",
                    "source": "florida_sunbiz",
                }
            )
    except Exception as exc:
        logger.debug("Florida Sunbiz parse error: %s", exc)
    return roles


@register("us_corporate_registry")
class UsCorporateRegistryCrawler(HttpxCrawler):
    """
    Searches US Secretary of State corporate registries for a person's
    officer, director, or registered agent roles.

    Uses OpenCorporates as the primary source across all US jurisdictions,
    then supplements with direct Florida Sunbiz scraping (the most open
    state portal for officer-level lookups).

    identifier: person full name

    Data keys returned:
        corporate_roles — list of {company_name, company_number, jurisdiction,
                          role, appointment_date, resignation_date, is_current,
                          company_status, registered_address, source}
        role_count      — integer
        active_count    — integer roles where is_current=True
        query           — original identifier
    """

    platform = "us_corporate_registry"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.92
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        roles: list[dict[str, Any]] = []

        # Primary: OpenCorporates officer search (all jurisdictions)
        oc_roles = await self._search_opencorporates(encoded)
        roles.extend(oc_roles)

        # Supplement: Florida Sunbiz direct scrape (officer names searchable)
        if not any(r["jurisdiction"] == "us_fl" for r in roles):
            fl_roles = await self._search_florida(query, encoded)
            roles.extend(fl_roles)

        active_count = sum(1 for r in roles if r.get("is_current"))

        return self._result(
            identifier,
            found=len(roles) > 0,
            corporate_roles=roles,
            role_count=len(roles),
            active_count=active_count,
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_opencorporates(self, encoded: str) -> list[dict[str, Any]]:
        """Query OpenCorporates officer search across all jurisdictions."""
        url = _OC_OFFICER_ALL.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None:
            return []
        if resp.status_code == 429:
            logger.info("OpenCorporates rate limited — skipping")
            return []
        if resp.status_code != 200:
            logger.debug("OpenCorporates officer search returned %s", resp.status_code)
            return []
        try:
            return _parse_oc_officers(resp.json())
        except Exception as exc:
            logger.warning("OpenCorporates parse error: %s", exc)
            return []

    async def _search_florida(self, query: str, encoded: str) -> list[dict[str, Any]]:
        """Scrape Florida Sunbiz entity name search."""
        url = _STATE_PORTALS["fl"].format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code != 200:
            return []
        return _parse_florida_html(resp.text, query)
