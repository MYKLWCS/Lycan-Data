"""
company_opencorporates.py — OpenCorporates free API scraper.

Searches the OpenCorporates public database for company registrations
and officer/director appointments globally.

Registered as "company_opencorporates".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE = "https://api.opencorporates.com/v0.4"
_COMPANY_SEARCH = _BASE + "/companies/search?q={query}&format=json"
_OFFICER_SEARCH = _BASE + "/officers/search?q={query}&format=json"


def _parse_companies(data: dict) -> list[dict[str, Any]]:
    """Extract normalised company records from an OpenCorporates search response."""
    companies: list[dict[str, Any]] = []
    results = data.get("results", {})
    for item in results.get("companies", []):
        co = item.get("company", item)
        companies.append(
            {
                "name":               co.get("name", ""),
                "company_number":     co.get("company_number", ""),
                "jurisdiction":       co.get("jurisdiction_code", ""),
                "registered_address": co.get("registered_address", {}).get("in_full", "")
                                      if isinstance(co.get("registered_address"), dict)
                                      else str(co.get("registered_address", "")),
                "status":             co.get("current_status", ""),
                "incorporation_date": co.get("incorporation_date", ""),
                "company_type":       co.get("company_type", ""),
                "url":                co.get("opencorporates_url", ""),
            }
        )
    return companies


def _parse_officers(data: dict) -> list[dict[str, Any]]:
    """Extract normalised officer records from an OpenCorporates officer search."""
    officers: list[dict[str, Any]] = []
    results = data.get("results", {})
    for item in results.get("officers", []):
        officer = item.get("officer", item)
        company = officer.get("company", {}) or {}
        officers.append(
            {
                "name":          officer.get("name", ""),
                "position":      officer.get("position", ""),
                "company_name":  company.get("name", ""),
                "jurisdiction":  company.get("jurisdiction_code", ""),
                "company_url":   company.get("opencorporates_url", ""),
                "start_date":    officer.get("start_date", ""),
                "end_date":      officer.get("end_date", ""),
            }
        )
    return officers


@register("company_opencorporates")
class OpenCorporatesCrawler(HttpxCrawler):
    """
    Searches OpenCorporates for company registrations and officer appointments.

    identifier: company name OR person name.
    Both company and officer searches are performed; results are merged.

    Data keys returned:
        companies    — list of company records
        officers     — list of officer/director appointment records
        result_count — total combined count
    """

    platform = "company_opencorporates"
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
                logger.warning("OpenCorporates company JSON parse error: %s", exc)

        # --- Officer search ---
        off_url = _OFFICER_SEARCH.format(query=encoded)
        off_resp = await self.get(off_url)
        if off_resp is not None and off_resp.status_code == 200:
            try:
                officers = _parse_officers(off_resp.json())
            except Exception as exc:
                logger.warning("OpenCorporates officer JSON parse error: %s", exc)

        result_count = len(companies) + len(officers)
        return self._result(
            identifier,
            found=result_count > 0,
            companies=companies,
            officers=officers,
            result_count=result_count,
        )
