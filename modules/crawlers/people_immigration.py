"""
people_immigration.py — Immigration court case lookup.

Searches for immigration court case information via CourtListener public API
(which includes immigration courts). Supports lookup by person name or
EOIR alien registration number (A-number: "A" + 9 digits).
Registered as "people_immigration".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# CourtListener REST API — immigration courts
_DOCKET_URL = (
    "https://www.courtlistener.com/api/rest/v4/dockets/"
    "?case_name={name}&court_type=bia&format=json&page_size=10"
)

# Alien Registration Number pattern: A followed by 8 or 9 digits
_A_NUMBER_RE = re.compile(r"^A?\d{8,9}$", re.IGNORECASE)


def _is_a_number(identifier: str) -> bool:
    """Return True if identifier looks like an alien registration number."""
    return bool(_A_NUMBER_RE.match(identifier.replace("-", "").replace(" ", "")))


def _parse_dockets(payload: dict) -> tuple[list[dict[str, Any]], int]:
    """Extract case records from CourtListener response."""
    results = payload.get("results", [])
    total = payload.get("count", len(results))

    cases: list[dict[str, Any]] = []
    for item in results:
        cases.append(
            {
                "case_name": item.get("case_name", ""),
                "docket_number": item.get("docket_number", ""),
                "court": item.get("court", ""),
                "date_filed": item.get("date_filed", ""),
                "date_terminated": item.get("date_terminated", ""),
                "absolute_url": "https://www.courtlistener.com" + item.get("absolute_url", ""),
            }
        )
    return cases, total


@register("people_immigration")
class PeopleImmigrationCrawler(HttpxCrawler):
    """
    Searches immigration court records via CourtListener public API.

    identifier:
        - Person full name (e.g. "Juan Rodriguez")
        - Alien Registration Number (e.g. "A123456789" or "123456789")

    Data keys returned:
        cases           — list of case records
        total           — total matching cases
        search_type     — "a_number" or "name"
        manual_search   — instructions for direct EOIR portal lookup
    """

    platform = "people_immigration"
    source_reliability = 0.90
    requires_tor = False

    _EOIR_PORTAL = "https://portal.eoir.justice.gov/InfoSystemUser/#/"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        if _is_a_number(query):
            search_type = "a_number"
            # A-numbers cannot be searched via CourtListener public API
            # without authentication; return structured guidance
            return self._result(
                identifier,
                found=False,
                error="a_number_requires_portal",
                search_type=search_type,
                cases=[],
                total=0,
                manual_search=(
                    f"Alien Registration Number searches require direct access to "
                    f"the EOIR automated case information system. "
                    f"Visit {self._EOIR_PORTAL} or call 1-800-898-7180 "
                    f"with A-Number: {query}"
                ),
            )

        search_type = "name"
        encoded = quote_plus(query)
        url = _DOCKET_URL.format(name=encoded)

        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                search_type=search_type,
                cases=[],
                total=0,
                manual_search=f"Manual search available at {self._EOIR_PORTAL}",
            )

        if resp.status_code == 403:
            # CourtListener may require auth for certain court types
            return self._result(
                identifier,
                found=False,
                error="auth_required",
                search_type=search_type,
                cases=[],
                total=0,
                manual_search=f"Manual search available at {self._EOIR_PORTAL}",
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                search_type=search_type,
                cases=[],
                total=0,
                manual_search=f"Manual search available at {self._EOIR_PORTAL}",
            )

        try:
            payload = resp.json()
            cases, total = _parse_dockets(payload)
        except Exception as exc:
            logger.warning("Immigration docket parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                search_type=search_type,
                cases=[],
                total=0,
                manual_search=f"Manual search available at {self._EOIR_PORTAL}",
            )

        return self._result(
            identifier,
            found=len(cases) > 0,
            search_type=search_type,
            cases=cases,
            total=total,
            manual_search=f"Manual search available at {self._EOIR_PORTAL}",
        )
