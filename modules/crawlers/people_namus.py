"""
people_namus.py — NamUs (National Missing and Unidentified Persons System) crawler.

Searches NamUs for missing persons or unidentified remains by name.
NamUs is a US DOJ/NIJ-managed database. The identifier is a full name;
the crawler splits it into first and last name for the API query.

Source: https://namus.nij.ojp.gov/
API:    https://www.namus.gov/api/CaseSets/NamUs/MissingPersons/Search (POST)
Registered as "people_namus".
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_NAMUS_URL = "https://www.namus.gov/api/CaseSets/NamUs/MissingPersons/Search"
_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}
_MAX_RESULTS = 20


def _parse_case(case: dict) -> dict[str, Any]:
    """Extract relevant fields from a NamUs missing person case record."""
    subject = case.get("subjectIdentification", {})
    circumstances = case.get("circumstances", {})
    sighting = case.get("sightings", [{}])
    last_seen = sighting[0] if sighting else {}
    return {
        "case_number": case.get("caseNumber"),
        "ncmec_number": case.get("ncmecNumber"),
        "first_name": subject.get("firstName", ""),
        "last_name": subject.get("lastName", ""),
        "middle_name": subject.get("middleName", ""),
        "nickname": subject.get("nicknames", ""),
        "date_of_birth": subject.get("dateOfBirth"),
        "age_at_disappearance": subject.get("computedMissingMinAge"),
        "sex": subject.get("sex", {}).get("name")
        if isinstance(subject.get("sex"), dict)
        else subject.get("sex", ""),
        "race": [r.get("name") for r in subject.get("races", []) if isinstance(r, dict)],
        "missing_date": circumstances.get("dateMissing"),
        "missing_city": last_seen.get("address", {}).get("city")
        if isinstance(last_seen.get("address"), dict)
        else "",
        "missing_state": last_seen.get("address", {}).get("state", {}).get("name")
        if isinstance(last_seen.get("address", {}).get("state"), dict)
        else "",
        "case_url": f"https://www.namus.gov/MissingPersons/Case#/{case.get('caseNumber')}",
    }


@register("people_namus")
class NamusCrawler(HttpxCrawler):
    """
    Searches NamUs Missing Persons database for a full name.

    The identifier is split on the first space into first/last name.
    For single-word identifiers, the value is used as last name only.

    identifier: full name (e.g. "Jane Doe")

    Data keys returned:
        cases       — list of matching missing person case records (up to 20)
        total       — total count from API
        query       — the name searched
    """

    platform = "people_namus"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        full_name = identifier.strip()
        if not full_name:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                cases=[],
                total=0,
                query=identifier,
            )

        parts = full_name.split(" ", 1)
        first_name = parts[0] if len(parts) >= 2 else ""
        last_name = parts[1] if len(parts) >= 2 else parts[0]

        payload = {
            "searchCriteria": {
                "firstName": first_name,
                "lastName": last_name,
            },
            "take": _MAX_RESULTS,
            "skip": 0,
            "sort": "relevance",
        }

        resp = await self.post(_NAMUS_URL, json=payload, headers=_HEADERS)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                cases=[],
                total=0,
                query=full_name,
            )

        if resp.status_code == 429:
            return self._result(
                identifier,
                found=False,
                error="rate_limited",
                cases=[],
                total=0,
                query=full_name,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                cases=[],
                total=0,
                query=full_name,
            )

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("NamUs JSON parse error for %r: %s", identifier, exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                cases=[],
                total=0,
                query=full_name,
            )

        raw_cases = data.get("results", [])
        total: int = data.get("total", len(raw_cases))
        cases = [_parse_case(c) for c in raw_cases[:_MAX_RESULTS]]

        return self._result(
            identifier,
            found=len(cases) > 0,
            cases=cases,
            total=total,
            query=full_name,
        )
