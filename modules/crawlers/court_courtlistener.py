"""
court_courtlistener.py — CourtListener REST API scraper.

Searches federal PACER cases and judicial opinions via the free CourtListener
public API. Also supports people (judge/attorney) lookup by name.

Registered as "court_courtlistener".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://www.courtlistener.com/api/rest/v3"
_SEARCH_URL = _BASE + "/search/?q={query}&type=p&format=json"
_OPINION_URL = _BASE + "/search/?q={query}&type=o&format=json"
_PEOPLE_URL = _BASE + "/people/?name_last={last}&name_first={first}&format=json"

_MAX_RESULTS = 10


def _split_name(identifier: str) -> tuple[str, str]:
    """
    Split 'First Last' into (first, last).
    Works for 2-word names; falls back to (identifier, "") for anything else.
    """
    parts = identifier.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return identifier.strip(), ""


def _parse_case_results(data: dict) -> list[dict[str, Any]]:
    """Extract normalised case records from a CourtListener search response."""
    cases: list[dict[str, Any]] = []
    for item in data.get("results", [])[:_MAX_RESULTS]:
        cases.append(
            {
                "case_name": item.get("caseName") or item.get("case_name", ""),
                "court": item.get("court", ""),
                "date_filed": item.get("dateFiled") or item.get("date_filed", ""),
                "url": "https://www.courtlistener.com" + item.get("absolute_url", "")
                if item.get("absolute_url", "").startswith("/")
                else item.get("absolute_url", ""),
                "docket_number": item.get("docketNumber") or item.get("docket_number", ""),
                "status": item.get("status", ""),
            }
        )
    return cases


@register("court_courtlistener")
class CourtListenerCrawler(HttpxCrawler):
    """
    Queries the CourtListener public REST API for federal court cases.

    identifier: person name ("John Smith") or freeform search term.

    Data keys returned:
        cases        — list of {case_name, court, date_filed, url, docket_number}
        case_count   — integer count of cases found
        query        — the original search term
    """

    platform = "court_courtlistener"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.92
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)
        cases: list[dict[str, Any]] = []

        # --- Primary: PACER/federal case search ---
        url = _SEARCH_URL.format(query=encoded)
        response = await self.get(url)

        if response is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                cases=[],
                case_count=0,
                query=query,
            )

        if response.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{response.status_code}",
                cases=[],
                case_count=0,
                query=query,
            )

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("CourtListener: JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="json_parse_error",
                cases=[],
                case_count=0,
                query=query,
            )

        cases = _parse_case_results(data)

        # --- Secondary: people search (judge/attorney) if name-shaped query ---
        first, last = _split_name(query)
        if first and last:
            people_url = _PEOPLE_URL.format(last=quote_plus(last), first=quote_plus(first))
            people_resp = await self.get(people_url)
            if people_resp is not None and people_resp.status_code == 200:
                try:
                    people_data = people_resp.json()
                    for person in people_data.get("results", [])[:5]:
                        # Surface notable people cases as supplementary entries
                        name = (
                            (person.get("name_first") or "") + " " + (person.get("name_last") or "")
                        ).strip()
                        if name:
                            cases.append(
                                {
                                    "case_name": f"[Person record] {name}",
                                    "court": person.get("court", ""),
                                    "date_filed": person.get("date_start", ""),
                                    "url": "https://www.courtlistener.com"
                                    + person.get("resource_uri", ""),
                                    "docket_number": "",
                                    "status": "people_record",
                                }
                            )
                except Exception as exc:
                    logger.debug("CourtListener people parse error: %s", exc)

        cases = cases[:_MAX_RESULTS]

        return self._result(
            identifier,
            found=len(cases) > 0,
            cases=cases,
            case_count=len(cases),
            query=query,
        )
