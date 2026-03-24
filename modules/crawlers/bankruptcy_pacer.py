"""
bankruptcy_pacer.py — Bankruptcy case search via CourtListener RECAP and CFPB complaints.

Searches for bankruptcy filings using:
  1. CourtListener RECAP mirror (indexes PACER data, free API)
  2. CFPB Consumer Complaint Database (active debt disputes)

Registered as "bankruptcy_pacer".

identifier: person name or company name
  e.g. "John Smith" or "Acme Corp"
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

_COURTLISTENER_RECAP_URL = (
    "https://www.courtlistener.com/api/rest/v3/search/"
    "?q={query}&type=r&format=json"
)
_CFPB_COMPLAINTS_URL = (
    "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
    "?field=all&size=10&search_term={query}"
)

_MAX_CASES      = 15
_MAX_COMPLAINTS = 10

# Chapter number extraction
_CHAPTER_RE = re.compile(r'(?:chapter|ch\.?)\s*(\d+)', re.I)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_recap_results(data: dict) -> list[dict[str, Any]]:
    """
    Parse CourtListener RECAP search results into normalised bankruptcy cases.

    RECAP type=r returns dockets with bankruptcy-specific metadata.
    """
    cases: list[dict[str, Any]] = []
    for item in data.get("results", [])[:_MAX_CASES]:
        case_name = item.get("caseName") or item.get("case_name", "")

        # Detect chapter from case name or nature of suit
        chapter = ""
        nos = str(item.get("nature_of_suit", ""))
        ch_m = _CHAPTER_RE.search(case_name + " " + nos)
        if ch_m:
            chapter = ch_m.group(1)
        elif "bankrupt" in case_name.lower():
            chapter = "7"  # most common default

        cases.append(
            {
                "case_name":   case_name,
                "court":       item.get("court", ""),
                "chapter":     chapter,
                "filed_date":  item.get("dateFiled") or item.get("date_filed", ""),
                "status":      item.get("status", ""),
                "assets":      item.get("assets", None),
                "liabilities": item.get("liabilities", None),
                "docket_url":  (
                    "https://www.courtlistener.com" + item.get("absolute_url", "")
                    if item.get("absolute_url", "").startswith("/")
                    else item.get("absolute_url", "")
                ),
            }
        )
    return cases


def _parse_cfpb_complaints(data: dict) -> list[dict[str, Any]]:
    """
    Parse CFPB Consumer Complaint Database API response.

    Returns simplified complaint records indicating active debt disputes.
    """
    complaints: list[dict[str, Any]] = []
    hits = data.get("hits", {})
    if isinstance(hits, dict):
        hit_list = hits.get("hits", [])
    else:
        hit_list = []

    for hit in hit_list[:_MAX_COMPLAINTS]:
        src = hit.get("_source", hit)
        complaints.append(
            {
                "product":      src.get("product", ""),
                "sub_product":  src.get("sub_product", ""),
                "issue":        src.get("issue", ""),
                "company":      src.get("company", ""),
                "date":         src.get("date_received", ""),
                "status":       src.get("company_response", src.get("status", "")),
                "complaint_id": src.get("complaint_id", ""),
            }
        )

    # Alternate response shape: { results: [...] }
    if not complaints:
        for item in data.get("results", [])[:_MAX_COMPLAINTS]:
            complaints.append(
                {
                    "product":      item.get("product", ""),
                    "sub_product":  item.get("sub_product", ""),
                    "issue":        item.get("issue", ""),
                    "company":      item.get("company", ""),
                    "date":         item.get("date_received", ""),
                    "status":       item.get("company_response", ""),
                    "complaint_id": item.get("complaint_id", ""),
                }
            )

    return complaints


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("bankruptcy_pacer")
class BankruptcyPacerCrawler(HttpxCrawler):
    """
    Searches for bankruptcy filings (CourtListener RECAP) and active debt
    disputes (CFPB complaints) for a person or company name.

    identifier: person or company name string.

    Data keys returned:
        query, cases (list of {case_name, court, chapter, filed_date, status, assets, liabilities}),
        case_count, complaints (list of {product, issue, company, date, status, complaint_id})
    """

    platform = "bankruptcy_pacer"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        if not query:
            return self._result(
                identifier, found=False, error="invalid_identifier",
                query=query, cases=[], case_count=0, complaints=[],
            )

        encoded = quote_plus(query)

        # --- Primary: CourtListener RECAP (bankruptcy dockets) ---
        recap_url = _COURTLISTENER_RECAP_URL.format(query=encoded)
        recap_resp = await self.get(recap_url)

        cases: list[dict[str, Any]] = []

        if recap_resp is None:
            return self._result(
                identifier, found=False, error="http_error",
                query=query, cases=[], case_count=0, complaints=[],
            )

        if recap_resp.status_code != 200:
            return self._result(
                identifier, found=False, error=f"http_{recap_resp.status_code}",
                query=query, cases=[], case_count=0, complaints=[],
            )

        try:
            recap_data = recap_resp.json()
        except Exception as exc:
            logger.warning("RECAP JSON parse error: %s", exc)
            return self._result(
                identifier, found=False, error="json_parse_error",
                query=query, cases=[], case_count=0, complaints=[],
            )

        cases = _parse_recap_results(recap_data)

        # --- Secondary: CFPB Consumer Complaint Database ---
        complaints: list[dict[str, Any]] = []
        cfpb_url = _CFPB_COMPLAINTS_URL.format(query=encoded)
        cfpb_resp = await self.get(cfpb_url)

        if cfpb_resp is not None and cfpb_resp.status_code == 200:
            try:
                cfpb_data = cfpb_resp.json()
                complaints = _parse_cfpb_complaints(cfpb_data)
            except Exception as exc:
                logger.debug("CFPB complaints parse error: %s", exc)

        found = len(cases) > 0 or len(complaints) > 0

        return self._result(
            identifier,
            found=found,
            query=query,
            cases=cases,
            case_count=len(cases),
            complaints=complaints,
        )
