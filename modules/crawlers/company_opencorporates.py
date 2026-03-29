"""
company_opencorporates.py — OpenCorporates scraper with API → website fallback.

Tries the free JSON API first. On 401/403 (rate-limited or key required),
falls back to scraping the OpenCorporates website HTML directly.

Registered as "company_opencorporates".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://api.opencorporates.com/v0.4"
_COMPANY_SEARCH = _BASE + "/companies/search?q={query}&format=json"
_OFFICER_SEARCH = _BASE + "/officers/search?q={query}&format=json"

# Website fallback URLs
_WEB_COMPANY_SEARCH = "https://opencorporates.com/companies?q={query}&utf8=%E2%9C%93"
_WEB_OFFICER_SEARCH = "https://opencorporates.com/officers?q={query}&utf8=%E2%9C%93"


def _parse_companies(data: dict) -> list[dict[str, Any]]:
    """Extract normalised company records from an OpenCorporates API response."""
    companies: list[dict[str, Any]] = []
    results = data.get("results", {})
    for item in results.get("companies", []):
        co = item.get("company", item)
        companies.append(
            {
                "name": co.get("name", ""),
                "company_number": co.get("company_number", ""),
                "jurisdiction": co.get("jurisdiction_code", ""),
                "registered_address": co.get("registered_address", {}).get("in_full", "")
                if isinstance(co.get("registered_address"), dict)
                else str(co.get("registered_address", "")),
                "status": co.get("current_status", ""),
                "incorporation_date": co.get("incorporation_date", ""),
                "company_type": co.get("company_type", ""),
                "url": co.get("opencorporates_url", ""),
            }
        )
    return companies


def _parse_officers(data: dict) -> list[dict[str, Any]]:
    """Extract normalised officer records from an OpenCorporates API response."""
    officers: list[dict[str, Any]] = []
    results = data.get("results", {})
    for item in results.get("officers", []):
        officer = item.get("officer", item)
        company = officer.get("company", {}) or {}
        officers.append(
            {
                "name": officer.get("name", ""),
                "position": officer.get("position", ""),
                "company_name": company.get("name", ""),
                "jurisdiction": company.get("jurisdiction_code", ""),
                "company_url": company.get("opencorporates_url", ""),
                "start_date": officer.get("start_date", ""),
                "end_date": officer.get("end_date", ""),
            }
        )
    return officers


def _parse_companies_html(html: str) -> list[dict[str, Any]]:
    """Parse company records from OpenCorporates website HTML."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        companies: list[dict[str, Any]] = []

        for row in soup.select("li.search-result, tr.company"):
            link = row.select_one("a.company_search_result, a[href*='/companies/']")
            if not link:
                continue
            name = link.get_text(strip=True)
            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://opencorporates.com{url}"

            text = row.get_text(" ", strip=True)
            jurisdiction = ""
            jur_match = re.search(r"(?:Jurisdiction|Company Number).*?([A-Z]{2}(?:_\w+)?)", text)
            if jur_match:
                jurisdiction = jur_match.group(1)

            status = ""
            status_match = re.search(r"(?:Status|status)[:\s]+([A-Za-z ]+)", text)
            if status_match:
                status = status_match.group(1).strip()

            companies.append(
                {
                    "name": name,
                    "company_number": "",
                    "jurisdiction": jurisdiction,
                    "registered_address": "",
                    "status": status,
                    "incorporation_date": "",
                    "company_type": "",
                    "url": url,
                }
            )
        return companies
    except Exception as exc:
        logger.warning("OpenCorporates HTML parse error: %s", exc)
        return []


def _parse_officers_html(html: str) -> list[dict[str, Any]]:
    """Parse officer records from OpenCorporates website HTML."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        officers: list[dict[str, Any]] = []

        for row in soup.select("li.search-result, tr.officer"):
            link = row.select_one("a[href*='/officers/']")
            if not link:
                continue
            name = link.get_text(strip=True)

            text = row.get_text(" ", strip=True)
            position = ""
            pos_match = re.search(r"(?:Position|Role)[:\s]+([A-Za-z ]+)", text)
            if pos_match:
                position = pos_match.group(1).strip()

            company_name = ""
            co_link = row.select_one("a[href*='/companies/']")
            if co_link:
                company_name = co_link.get_text(strip=True)

            officers.append(
                {
                    "name": name,
                    "position": position,
                    "company_name": company_name,
                    "jurisdiction": "",
                    "company_url": "",
                    "start_date": "",
                    "end_date": "",
                }
            )
        return officers
    except Exception as exc:
        logger.warning("OpenCorporates officer HTML parse error: %s", exc)
        return []


@register("company_opencorporates")
class OpenCorporatesCrawler(HttpxCrawler):
    """
    Searches OpenCorporates for company registrations and officer appointments.

    Strategy: API first, website HTML fallback on 401/403.

    identifier: company name OR person name.
    Both company and officer searches are performed; results are merged.
    """

    platform = "company_opencorporates"
    category = CrawlerCategory.BUSINESS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        # Try API first, fall back to website on auth errors
        companies, officers = await self._try_api(encoded)
        both_failed = companies is None and officers is None
        if both_failed:
            # API returned 401/403 or HTTP error — fall back to website scraping
            logger.info("OpenCorporates API auth failed, falling back to website scrape")
            companies, officers = await self._try_website(encoded)

        companies = companies or []
        officers = officers or []
        result_count = len(companies) + len(officers)

        error = "http_error" if both_failed and companies == [] and officers == [] else None

        return self._result(
            identifier,
            found=result_count > 0,
            error=error,
            companies=companies,
            officers=officers,
            result_count=result_count,
        )

    async def _try_api(
        self, encoded_query: str
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
        """Try the JSON API. Returns (None, None) on 401/403."""
        co_url = _COMPANY_SEARCH.format(query=encoded_query)
        co_resp = await self.get(co_url)

        if co_resp is None:
            return None, None

        if co_resp.status_code in (401, 403):
            return None, None

        companies: list[dict[str, Any]] = []
        if co_resp.status_code == 200:
            try:
                companies = _parse_companies(co_resp.json())
            except Exception as exc:
                logger.warning("OpenCorporates company JSON parse error: %s", exc)

        officers: list[dict[str, Any]] = []
        off_url = _OFFICER_SEARCH.format(query=encoded_query)
        off_resp = await self.get(off_url)
        if off_resp is not None and off_resp.status_code == 200:
            try:
                officers = _parse_officers(off_resp.json())
            except Exception as exc:
                logger.warning("OpenCorporates officer JSON parse error: %s", exc)

        return companies, officers

    async def _try_website(
        self, encoded_query: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Scrape the OpenCorporates website HTML as a fallback."""
        companies: list[dict[str, Any]] = []
        officers: list[dict[str, Any]] = []

        co_url = _WEB_COMPANY_SEARCH.format(query=encoded_query)
        co_resp = await self.get(
            co_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html",
            },
        )
        if co_resp is not None and co_resp.status_code == 200:
            companies = _parse_companies_html(co_resp.text)

        off_url = _WEB_OFFICER_SEARCH.format(query=encoded_query)
        off_resp = await self.get(
            off_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html",
            },
        )
        if off_resp is not None and off_resp.status_code == 200:
            officers = _parse_officers_html(off_resp.text)

        return companies, officers
