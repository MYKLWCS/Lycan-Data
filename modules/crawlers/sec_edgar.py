"""
sec_edgar.py — SEC EDGAR unified search crawler.

Covers:
  - Company lookup via EDGAR company search (10-K, 8-K, proxy filings)
  - Person lookup via EDGAR full-text search (DEF 14A, Form 4, 8-K)
  - CIK resolution for confirmed companies

Endpoint: https://efts.sec.gov/LATEST/search-index (free, no auth)
Rate limit: SEC asks ≤ 10 requests/second; we stay well below that.

Registered as "sec_edgar".
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

# EDGAR full-text search (EFTS) — broad filing search
_EFTS_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%22{query}%22&forms={forms}&dateRange=custom&startdt=2010-01-01"
    "&hits.hits.total.value=true&hits.hits._source.period_of_report=true"
)

# EDGAR company name search — returns Atom XML
_COMPANY_SEARCH_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?company={name}&CIK=&type=&dateb=&owner=include"
    "&count=10&search_text=&action=getcompany&output=atom"
)

# EDGAR submissions endpoint for a known CIK
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Default form types for broad person/company search
_DEFAULT_FORMS = "10-K,8-K,DEF%2014A,4,SC%2013G,SC%2013D"

_HEADERS = {
    "User-Agent": "LycanOSINT research@wolfcorporation.com",
    "Accept": "application/json",
}


def _parse_efts_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract filing records from EDGAR EFTS response."""
    hits = []
    try:
        for hit in (payload.get("hits") or {}).get("hits") or []:
            src = hit.get("_source") or {}
            hits.append(
                {
                    "accession_no": src.get("file_num") or hit.get("_id"),
                    "form_type": src.get("form_type"),
                    "filed_at": src.get("period_of_report") or src.get("file_date"),
                    "entity_name": src.get("entity_name") or src.get("display_names"),
                    "cik": src.get("entity_id"),
                    "description": src.get("file_description"),
                    "url": (
                        "https://www.sec.gov/Archives/edgar/data/"
                        + str(src.get("entity_id", ""))
                        + "/"
                        + str(hit.get("_id", "")).replace("-", "")
                        + "/"
                    )
                    if src.get("entity_id") and hit.get("_id")
                    else None,
                }
            )
    except Exception as exc:
        logger.debug("EFTS parse error: %s", exc)
    return hits


def _parse_company_atom(xml_text: str) -> list[dict[str, Any]]:
    """Parse EDGAR company search Atom feed."""
    import xml.etree.ElementTree as ET

    companies = []
    ns = "http://www.w3.org/2005/Atom"
    try:
        root = ET.fromstring(xml_text)
        for entry in root.findall(f"{{{ns}}}entry"):
            cik_el = entry.find(f"{{{ns}}}id")
            name_el = entry.find(f"{{{ns}}}company-name")
            sic_el = entry.find(f"{{{ns}}}assigned-sic-desc")
            state_el = entry.find(f"{{{ns}}}state-of-incorporation")
            link_el = entry.find(f"{{{ns}}}link")
            companies.append(
                {
                    "cik": (cik_el.text or "").split("/")[-1].lstrip("0")
                    if cik_el is not None
                    else None,
                    "company_name": name_el.text if name_el is not None else None,
                    "industry": sic_el.text if sic_el is not None else None,
                    "state_of_incorporation": state_el.text if state_el is not None else None,
                    "filing_page": link_el.get("href") if link_el is not None else None,
                }
            )
    except Exception as exc:
        logger.debug("EDGAR Atom parse error: %s", exc)
    return companies


@register("sec_edgar")
class SecEdgarCrawler(HttpxCrawler):
    """
    Unified SEC EDGAR crawler covering corporate filings and insider trades.

    identifier modes (auto-detected):
      - Company name / ticker: broad company search + recent filings
      - Person name (contains space): EFTS full-text search across all form types

    Returns filing records, CIK numbers, and company metadata.
    Free API — no authentication required. SEC rate limit: ≤ 10 req/s.
    """

    platform = "sec_edgar"
    category = CrawlerCategory.FINANCIAL
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=5, cooldown_seconds=0.5)
    source_reliability = 0.95  # Official US government source
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        results: dict[str, Any] = {
            "query": query,
            "filings": [],
            "companies": [],
        }

        # ── 1. EFTS full-text search ────────────────────────────────────────
        efts_url = _EFTS_URL.format(query=encoded, forms=_DEFAULT_FORMS)
        efts_resp = await self.get(efts_url, headers=_HEADERS)
        if efts_resp and efts_resp.status_code == 200:
            try:
                payload = efts_resp.json()
                results["filings"] = _parse_efts_hits(payload)
                total = (payload.get("hits") or {}).get("total", {}).get("value", 0)
                results["total_filing_count"] = total
            except Exception as exc:
                logger.debug("EFTS JSON error for %s: %s", query, exc)

        # ── 2. Company search (Atom) ─────────────────────────────────────────
        company_url = _COMPANY_SEARCH_URL.format(name=encoded)
        co_resp = await self.get(
            company_url,
            headers={
                "User-Agent": "LycanOSINT research@wolfcorporation.com",
                "Accept": "application/atom+xml,text/xml,*/*",
            },
        )
        if co_resp and co_resp.status_code == 200:
            companies = _parse_company_atom(co_resp.text)
            results["companies"] = companies

            # ── 3. If we found exactly one company, fetch its submissions ───
            if len(companies) == 1 and companies[0].get("cik"):
                cik_padded = companies[0]["cik"].zfill(10)
                sub_url = _SUBMISSIONS_URL.format(cik=cik_padded)
                sub_resp = await self.get(sub_url, headers=_HEADERS)
                if sub_resp and sub_resp.status_code == 200:
                    try:
                        sub_data = sub_resp.json()
                        recent = sub_data.get("filings", {}).get("recent", {})
                        forms = recent.get("form", [])
                        dates = recent.get("filingDate", [])
                        accessions = recent.get("accessionNumber", [])
                        results["recent_filings"] = [
                            {"form": f, "date": d, "accession": a}
                            for f, d, a in zip(forms[:20], dates[:20], accessions[:20])
                        ]
                        results["company_detail"] = {
                            "name": sub_data.get("name"),
                            "sic": sub_data.get("sic"),
                            "sic_description": sub_data.get("sicDescription"),
                            "tickers": sub_data.get("tickers"),
                            "exchanges": sub_data.get("exchanges"),
                            "ein": sub_data.get("ein"),
                            "state_of_incorporation": sub_data.get("stateOfIncorporation"),
                            "fiscal_year_end": sub_data.get("fiscalYearEnd"),
                            "phone": sub_data.get("phone"),
                            "addresses": sub_data.get("addresses"),
                        }
                    except Exception as exc:
                        logger.debug("Submissions JSON error: %s", exc)

        found = bool(results["filings"] or results["companies"])
        return self._result(identifier, found=found, **results)
