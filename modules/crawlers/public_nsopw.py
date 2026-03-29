"""
public_nsopw.py — NSOPW (National Sex Offender Public Website) scraper.

Uses the NSOPW live-search AJAX API to look up registered sex offenders
by name across all participating state registries.

API endpoint (POST JSON):
  https://www.nsopw.gov/en/Search/Verify

Registered as "public_nsopw".

identifier: "First Last" name.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.utils import split_name

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.nsopw.gov/en/Search/Verify"
_MAX_RESULTS = 50

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.nsopw.gov/en/search/results",
    "Origin": "https://www.nsopw.gov",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_offenders(data: dict) -> list[dict[str, Any]]:
    """
    Normalise NSOPW API response into a list of offender records.

    Expected JSON shape:
      {TotalRecordCount, Records: [{FullName, Address, City, State, DOB, Conviction}]}
    """
    offenders: list[dict[str, Any]] = []
    for item in data.get("Records", [])[:_MAX_RESULTS]:
        offenders.append(
            {
                "name": item.get("FullName", ""),
                "address": item.get("Address", ""),
                "city": item.get("City", ""),
                "state": item.get("State", ""),
                "dob": item.get("DOB", ""),
                "conviction": item.get("Conviction", ""),
            }
        )
    return offenders


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("public_nsopw")
class PublicNSOPWCrawler(HttpxCrawler):
    """
    Queries the NSOPW public API for registered sex offenders by name.

    identifier: full name, e.g. "John Smith"

    Data keys returned:
        offenders    — list of {name, address, city, state, dob, conviction}
        result_count — integer
        query        — original identifier
    """

    platform = "public_nsopw"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        first, last = split_name(query)

        payload = {
            "firstName": first,
            "lastName": last,
            "stateId": "",
            "county": "",
            "city": "",
            "zipCode": "",
        }

        response = await self.post(
            _SEARCH_URL,
            json=payload,
            headers=_HEADERS,
        )

        if response is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                offenders=[],
                result_count=0,
                query=query,
            )

        if response.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{response.status_code}",
                offenders=[],
                result_count=0,
                query=query,
            )

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("NSOPW: JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="json_parse_error",
                offenders=[],
                result_count=0,
                query=query,
            )

        offenders = _parse_offenders(data)
        result_count = data.get("TotalRecordCount", len(offenders))

        return self._result(
            identifier,
            found=len(offenders) > 0,
            offenders=offenders,
            result_count=result_count,
            query=query,
        )
