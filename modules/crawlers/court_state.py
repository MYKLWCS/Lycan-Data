"""
court_state.py — State court portal scraper (Texas + New York).

Uses Playwright to query state court public search portals that accept
GET parameters, then parses HTML result tables.

Registered as "court_state".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# Public court portals with GET-parameter search
_TX_URL = "https://publicsite.courts.state.tx.us/HomeSearch/Search?SearchMode=0&partyName={name}"
_NY_URL = (
    "https://iapps.courts.state.ny.us/webcivil/FCASSearch?param=I&party={name}&casetype=A&county="
)


def _parse_table_rows(html: str, state: str) -> list[dict[str, Any]]:
    """
    Parse an HTML result table from a state court portal.

    Looks for <table> → <tr> rows and extracts cells into normalised dicts.
    The exact columns vary per portal; we capture whatever is available.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("BeautifulSoup not installed; cannot parse court HTML")
        return []

    soup = BeautifulSoup(html, "html.parser")
    cases: list[dict[str, Any]] = []

    # Find the main results table — look for a table with 4+ columns
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Derive headers from the first row
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True).lower() for c in header_cells]

        if len(headers) < 2:
            continue

        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells:
                continue
            record: dict[str, Any] = {"state": state}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                record[key] = cell.get_text(strip=True)

            # Normalise common column name variants
            record.setdefault(
                "case_number",
                record.pop("case no.", record.pop("case #", record.pop("case number", ""))),
            )
            record.setdefault("case_type", record.pop("case type", record.pop("type", "")))
            record.setdefault("filing_date", record.pop("date filed", record.pop("filed", "")))
            record.setdefault("parties", record.pop("party name", record.pop("parties", "")))
            record.setdefault("court", record.pop("court", ""))

            if any(record.values()):
                cases.append(record)

    return cases


@register("court_state")
class CourtStateCrawler(PlaywrightCrawler):
    """
    Playwright scraper for Texas and New York public court portals.

    identifier: full person name, e.g. "John Smith"

    Data keys returned:
        cases      — list of case records (keys vary by state)
        case_count — integer
        state      — "TX" or "NY" (the first portal that returned results)
        query      — original identifier
    """

    platform = "court_state"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        all_cases: list[dict[str, Any]] = []
        states_checked: list[str] = []

        # --- Texas ---
        tx_url = _TX_URL.format(name=encoded)
        tx_cases = await self._scrape_portal(tx_url, state="TX")
        states_checked.append("TX")
        all_cases.extend(tx_cases)

        # --- New York ---
        ny_url = _NY_URL.format(name=encoded)
        ny_cases = await self._scrape_portal(ny_url, state="NY")
        states_checked.append("NY")
        all_cases.extend(ny_cases)

        return self._result(
            identifier,
            found=len(all_cases) > 0,
            cases=all_cases,
            case_count=len(all_cases),
            state=",".join(states_checked),
            query=query,
        )

    async def _scrape_portal(self, url: str, state: str) -> list[dict[str, Any]]:
        """Navigate to a portal URL and parse its result table."""
        try:
            async with self.page(url) as page:
                await page.wait_for_load_state("networkidle", timeout=15000)
                html = await page.content()
            return _parse_table_rows(html, state)
        except Exception as exc:
            logger.warning("court_state %s portal error: %s", state, exc)
            return []
