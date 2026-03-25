"""
fara_scraper.py — Foreign Agents Registration Act (FARA) database search.

Queries the FARA eFile portal search API at:
  https://efile.fara.gov/ords/fara/f?p=API:SEARCH

Returns registrant name, foreign principal, registration dates, activities,
and financial disclosure summary for matches on the given person/entity name.

Registered as "fara_scraper".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# FARA eFile API — JSON search endpoint
_FARA_API = "https://efile.fara.gov/ords/fara/f?p=API:SEARCH:::::P_SEARCH_TEXT:{query}"

# Alternative REST endpoint used by the FARA developer portal
_FARA_REST = (
    "https://efile.fara.gov/api/public/search/registrations?searchText={query}&page=1&pageSize=50"
)

_MATCH_THRESHOLD = 0.5


def _word_overlap(query: str, candidate: str) -> float:
    """Simple word-overlap score (0.0–1.0) for name matching."""
    q = set(query.lower().split())
    c = set(candidate.lower().split())
    if not q:
        return 0.0
    return len(q & c) / len(q)


def _parse_rest_response(data: Any, query: str) -> list[dict[str, Any]]:
    """
    Parse the FARA REST API JSON response into normalised registration records.

    The API returns a list of registration objects (structure may vary by
    firmware version). We normalise to the documented field set.
    """
    registrations: list[dict[str, Any]] = []

    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # May be wrapped: {"items": [...]} or {"registrations": [...]}
        items = data.get("items") or data.get("registrations") or data.get("results") or []

    for item in items:
        if not isinstance(item, dict):
            continue

        reg_name: str = (
            item.get("registrantName") or item.get("registrant_name") or item.get("name", "")
        )
        fp_name: str = (
            item.get("foreignPrincipalName")
            or item.get("foreign_principal_name")
            or item.get("foreignPrincipal", "")
        )
        fp_country: str = (
            item.get("foreignPrincipalCountry")
            or item.get("country")
            or item.get("foreignPrincipalNationality", "")
        )
        reg_number: str = (
            item.get("registrationNumber")
            or item.get("registration_number")
            or item.get("regNumber", "")
        )
        reg_date: str = (
            item.get("registrationDate")
            or item.get("registration_date")
            or item.get("dateOfRegistration", "")
        )
        term_date: str = (
            item.get("terminationDate")
            or item.get("termination_date")
            or item.get("dateOfTermination", "")
        )
        activities: str = (
            item.get("activitiesDescription")
            or item.get("activities_description")
            or item.get("activities", "")
        )
        is_active: bool = not bool(term_date)

        # Filter by name match when we have a registrant name
        candidate = reg_name or fp_name
        if candidate and _word_overlap(query, candidate) < _MATCH_THRESHOLD:
            continue

        registrations.append(
            {
                "registrant_name": reg_name,
                "foreign_principal_name": fp_name,
                "foreign_principal_country": fp_country,
                "registration_number": str(reg_number),
                "registration_date": reg_date,
                "termination_date": term_date,
                "activities": activities,
                "is_active": is_active,
            }
        )

    return registrations


def _parse_html_table(html: str, query: str) -> list[dict[str, Any]]:
    """
    Fallback: parse the FARA search HTML results table with BeautifulSoup.
    Used when the REST endpoint returns non-JSON or an unexpected format.
    """
    registrations: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            if not any(
                kw in " ".join(headers) for kw in ("registrant", "principal", "registration")
            ):
                continue
            for row in rows[1:]:
                cells = row.find_all("td")
                if not cells:
                    continue
                record: dict[str, str] = {
                    headers[i] if i < len(headers) else f"col_{i}": cell.get_text(strip=True)
                    for i, cell in enumerate(cells)
                }
                reg_name = record.get("registrant name") or record.get("registrant", "")
                fp_name = record.get("foreign principal") or record.get("principal", "")
                fp_country = record.get("country", "")
                reg_date = record.get("registration date") or record.get("date registered", "")
                term_date = record.get("termination date") or record.get("date terminated", "")
                reg_number = record.get("registration number") or record.get("reg #", "")

                candidate = reg_name or fp_name
                if candidate and _word_overlap(query, candidate) < _MATCH_THRESHOLD:
                    continue

                registrations.append(
                    {
                        "registrant_name": reg_name,
                        "foreign_principal_name": fp_name,
                        "foreign_principal_country": fp_country,
                        "registration_number": reg_number,
                        "registration_date": reg_date,
                        "termination_date": term_date,
                        "activities": "",
                        "is_active": not bool(term_date),
                    }
                )
            if registrations:
                break
    except Exception as exc:
        logger.debug("FARA HTML parse error: %s", exc)
    return registrations


@register("fara_scraper")
class FaraScraperCrawler(HttpxCrawler):
    """
    Searches the FARA eFile database for Foreign Agent registrations.

    Tries the documented REST API first; falls back to HTML table scraping
    if the REST endpoint returns an unexpected payload.

    identifier: person or organisation name

    Data keys returned:
        fara_registrations — list of {registrant_name, foreign_principal_name,
                             foreign_principal_country, registration_number,
                             registration_date, termination_date, activities,
                             is_active}
        total_count        — integer
        query              — original identifier
    """

    platform = "fara_scraper"
    source_reliability = 0.95
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        registrations = await self._try_rest_api(query, encoded)

        if not registrations:
            registrations = await self._try_html_search(query, encoded)

        return self._result(
            identifier,
            found=len(registrations) > 0,
            fara_registrations=registrations,
            total_count=len(registrations),
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _try_rest_api(self, query: str, encoded: str) -> list[dict[str, Any]]:
        """Attempt the FARA REST JSON endpoint."""
        url = _FARA_REST.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            logger.debug("FARA REST API returned %s", resp.status_code if resp else "None")
            return []
        try:
            data = resp.json()
        except Exception as exc:
            logger.debug("FARA REST JSON decode error: %s", exc)
            return []
        return _parse_rest_response(data, query)

    async def _try_html_search(self, query: str, encoded: str) -> list[dict[str, Any]]:
        """Fallback: scrape the FARA eFile HTML search portal."""
        url = _FARA_API.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code != 200:
            logger.debug("FARA HTML search returned %s", resp.status_code if resp else "None")
            return []
        return _parse_html_table(resp.text, query)
