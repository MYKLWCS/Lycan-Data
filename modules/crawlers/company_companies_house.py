"""
company_companies_house.py — UK Companies House free API scraper.

Searches the Companies House public API for UK company registrations
and officer/director appointments. No API key required for basic search.

Registered as "company_companies_house".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE = "https://api.company-information.service.gov.uk"
_COMPANY_SEARCH = _BASE + "/search/companies?q={query}&items_per_page=10"
_OFFICER_SEARCH = _BASE + "/search/officers?q={query}&items_per_page=10"


def _parse_companies(data: dict) -> list[dict[str, Any]]:
    """Extract normalised company records from a Companies House response."""
    companies: list[dict[str, Any]] = []
    for item in data.get("items", []):
        companies.append(
            {
                "name":             item.get("title", ""),
                "company_number":   item.get("company_number", ""),
                "status":           item.get("company_status", ""),
                "incorporation_date": item.get("date_of_creation", ""),
                "address":          item.get("address_snippet", ""),
                "company_type":     item.get("company_type", ""),
                "url":              "https://find-and-update.company-information.service.gov.uk/company/"
                                    + item.get("company_number", ""),
            }
        )
    return companies


def _parse_officers(data: dict) -> list[dict[str, Any]]:
    """Extract normalised officer records from a Companies House officer search."""
    officers: list[dict[str, Any]] = []
    for item in data.get("items", []):
        dob = item.get("date_of_birth", {}) or {}
        officers.append(
            {
                "name":              item.get("title", ""),
                "dob_month":         dob.get("month", ""),
                "dob_year":          dob.get("year", ""),
                "appointment_count": item.get("appointment_count", 0),
                "links":             item.get("links", {}).get("self", ""),
            }
        )
    return officers


@register("company_companies_house")
class CompaniesHouseCrawler(HttpxCrawler):
    """
    Searches UK Companies House for company registrations and officers.

    identifier: company name or person name.
    Both endpoints are queried and results merged.

    Data keys returned:
        companies    — list of company records
        officers     — list of officer appointment records
        result_count — total combined count
    """

    platform = "company_companies_house"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)
        companies: list[dict[str, Any]] = []
        officers: list[dict[str, Any]] = []

        # --- Company search ---
        co_url = _COMPANY_SEARCH.format(query=encoded)
        co_resp = await self.get(co_url)

        if co_resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                companies=[],
                officers=[],
                result_count=0,
            )

        if co_resp.status_code == 200:
            try:
                companies = _parse_companies(co_resp.json())
            except Exception as exc:
                logger.warning("Companies House company JSON parse error: %s", exc)

        # --- Officer search ---
        off_url = _OFFICER_SEARCH.format(query=encoded)
        off_resp = await self.get(off_url)
        if off_resp is not None and off_resp.status_code == 200:
            try:
                officers = _parse_officers(off_resp.json())
            except Exception as exc:
                logger.warning("Companies House officer JSON parse error: %s", exc)

        result_count = len(companies) + len(officers)
        return self._result(
            identifier,
            found=result_count > 0,
            companies=companies,
            officers=officers,
            result_count=result_count,
        )
