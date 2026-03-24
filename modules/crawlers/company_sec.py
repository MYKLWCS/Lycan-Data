"""
company_sec.py — SEC EDGAR company filing scraper.

Queries the SEC EDGAR company search Atom feed for 10-K, 8-K, and proxy
filings associated with a company or person name.

Registered as "company_sec".
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# EDGAR company search — returns Atom XML
_EDGAR_COMPANY_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?company={name}&CIK=&type=10-K&dateb=&owner=include"
    "&count=10&search_text=&action=getcompany&output=atom"
)

# EDGAR full-text search for person names
_EDGAR_FTS_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%22{query}%22&forms=DEF%2014A,8-K"
)

# Atom namespace used by EDGAR feeds
_ATOM_NS = "http://www.w3.org/2005/Atom"


def _parse_atom_feed(xml_text: str) -> list[dict[str, Any]]:
    """
    Parse an EDGAR Atom feed and return a list of filing records.

    Expected entry structure:
        <entry>
          <title>10-K for ACME CORP (CIK: 0001234567)</title>
          <updated>2024-03-15T00:00:00-04:00</updated>
          <link href="https://www.sec.gov/cgi-bin/browse-edgar?..."/>
          ...
          <category label="10-K" .../>
          <content>CIK: 0001234567 ...</content>
        </entry>
    """
    filings: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("SEC EDGAR: Atom XML parse error: %s", exc)
        return filings

    ns = {"atom": _ATOM_NS}

    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        updated_el = entry.find("atom:updated", ns)
        link_el = entry.find("atom:link", ns)
        category_el = entry.find("atom:category", ns)
        content_el = entry.find("atom:content", ns)

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        date = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
        url = link_el.get("href", "") if link_el is not None else ""
        form_type = (
            category_el.get("label", "") or category_el.get("term", "")
            if category_el is not None else ""
        )
        content_text = (
            content_el.text.strip() if content_el is not None and content_el.text else ""
        )

        # Extract company name and CIK from the title or content
        company = title
        cik = ""
        if "CIK" in content_text:
            for part in content_text.split():
                if part.isdigit() and len(part) >= 7:
                    cik = part
                    break

        filings.append(
            {
                "company":   company,
                "cik":       cik,
                "form_type": form_type,
                "date":      date[:10] if len(date) >= 10 else date,
                "url":       url,
            }
        )

    return filings


@register("company_sec")
class SECEdgarCrawler(HttpxCrawler):
    """
    Searches SEC EDGAR for company filings (10-K, 8-K, proxy statements).

    identifier: company name or person name.

    Data keys returned:
        filings      — list of {company, cik, form_type, date, url}
        result_count — integer
    """

    platform = "company_sec"
    source_reliability = 0.88
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)
        filings: list[dict[str, Any]] = []

        # --- Primary: EDGAR company search (Atom feed) ---
        edgar_url = _EDGAR_COMPANY_URL.format(name=encoded)
        response = await self.get(edgar_url)

        if response is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                filings=[],
                result_count=0,
            )

        if response.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{response.status_code}",
                filings=[],
                result_count=0,
            )

        filings = _parse_atom_feed(response.text)

        # --- Secondary: full-text search for person/company mentions ---
        fts_url = _EDGAR_FTS_URL.format(query=encoded)
        fts_resp = await self.get(fts_url)
        if fts_resp is not None and fts_resp.status_code == 200:
            try:
                fts_data = fts_resp.json()
                for hit in fts_data.get("hits", {}).get("hits", [])[:5]:
                    src = hit.get("_source", {})
                    filings.append(
                        {
                            "company":   src.get("entity_name", ""),
                            "cik":       src.get("file_num", ""),
                            "form_type": src.get("form_type", ""),
                            "date":      src.get("file_date", ""),
                            "url":       "https://www.sec.gov/Archives/" + src.get("file_path", ""),
                        }
                    )
            except Exception as exc:
                logger.debug("SEC FTS parse error: %s", exc)

        return self._result(
            identifier,
            found=len(filings) > 0,
            filings=filings,
            result_count=len(filings),
        )
