"""
Tests for Court Records scrapers — Tasks 23.
  - CourtListenerCrawler  (court_courtlistener)
  - CourtStateCrawler     (court_state)

12 tests total — HTTP calls are mocked; Playwright calls are mocked.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

# Trigger @register decorators
import modules.crawlers.court_courtlistener  # noqa: F401
import modules.crawlers.court_state  # noqa: F401
from modules.crawlers.court_courtlistener import (
    CourtListenerCrawler,
    _parse_case_results,
    _split_name,
)
from modules.crawlers.court_state import (
    CourtStateCrawler,
    _parse_table_rows,
)
from modules.crawlers.registry import is_registered

# ===========================================================================
# Helpers
# ===========================================================================


def _mock_resp(status: int = 200, json_data: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


SAMPLE_CL_JSON = {
    "count": 2,
    "results": [
        {
            "caseName": "Smith v. Jones",
            "court": "txnd",
            "dateFiled": "2023-04-15",
            "absolute_url": "/docket/12345/",
            "docketNumber": "3:23-cv-01234",
            "status": "Terminated",
        },
        {
            "caseName": "State v. Smith",
            "court": "ca9",
            "dateFiled": "2022-11-01",
            "absolute_url": "/docket/67890/",
            "docketNumber": "22-56789",
            "status": "Active",
        },
    ],
}

SAMPLE_CL_PEOPLE_JSON = {
    "count": 1,
    "results": [
        {
            "name_first": "John",
            "name_last": "Smith",
            "resource_uri": "/api/rest/v3/people/42/",
            "court": "txnd",
            "date_start": "2010-01-01",
        }
    ],
}

SAMPLE_TX_HTML = """
<html><body>
<table>
  <tr><th>Case No.</th><th>Party Name</th><th>Court</th><th>Date Filed</th><th>Case Type</th></tr>
  <tr><td>2023-TX-001</td><td>SMITH, JOHN</td><td>Dallas District</td><td>2023-01-10</td><td>Civil</td></tr>
  <tr><td>2022-TX-999</td><td>SMITH, JOHN</td><td>Travis County</td><td>2022-06-05</td><td>Criminal</td></tr>
</table>
</body></html>
"""


# ===========================================================================
# 1. Registry tests
# ===========================================================================


def test_courtlistener_registered():
    assert is_registered("court_courtlistener")


def test_court_state_registered():
    assert is_registered("court_state")


# ===========================================================================
# 2. _split_name utility
# ===========================================================================


def test_split_name_two_words():
    first, last = _split_name("John Smith")
    assert first == "John"
    assert last == "Smith"


def test_split_name_single_word():
    first, last = _split_name("Acme")
    assert first == "Acme"
    assert last == ""


def test_split_name_three_words():
    """Three-word name: first word → first, last word → last."""
    first, last = _split_name("Mary Jane Watson")
    assert first == "Mary"
    assert last == "Watson"


# ===========================================================================
# 3. _parse_case_results
# ===========================================================================


def test_parse_case_results_extracts_fields():
    cases = _parse_case_results(SAMPLE_CL_JSON)
    assert len(cases) == 2
    assert cases[0]["case_name"] == "Smith v. Jones"
    assert cases[0]["court"] == "txnd"
    assert cases[0]["docket_number"] == "3:23-cv-01234"
    assert "courtlistener.com" in cases[0]["url"]


def test_parse_case_results_empty():
    cases = _parse_case_results({"count": 0, "results": []})
    assert cases == []


# ===========================================================================
# 4. CourtListenerCrawler — scrape()
# ===========================================================================


@pytest.mark.asyncio
async def test_courtlistener_found():
    """Cases returned by API appear in result."""
    crawler = CourtListenerCrawler()
    mock_main = _mock_resp(200, json_data=SAMPLE_CL_JSON)
    mock_people = _mock_resp(200, json_data=SAMPLE_CL_PEOPLE_JSON)

    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_main, mock_people])):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["case_count"] >= 2
    assert len(result.data["cases"]) >= 2


@pytest.mark.asyncio
async def test_courtlistener_not_found():
    """Empty results → found=False."""
    crawler = CourtListenerCrawler()
    mock_main = _mock_resp(200, json_data={"count": 0, "results": []})
    mock_people = _mock_resp(200, json_data={"count": 0, "results": []})

    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_main, mock_people])):
        result = await crawler.scrape("Nobody Zzzxxx")

    assert result.found is False
    assert result.data["case_count"] == 0


@pytest.mark.asyncio
async def test_courtlistener_http_error():
    """HTTP failure → error result."""
    crawler = CourtListenerCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert result.data.get("error") == "http_error" or result.error is not None


@pytest.mark.asyncio
async def test_courtlistener_bad_status():
    """Non-200 status → error result."""
    crawler = CourtListenerCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
        result = await crawler.scrape("John Smith")
    assert result.found is False


@pytest.mark.asyncio
async def test_courtlistener_json_parse_error():
    """Invalid JSON → error result, no crash."""
    crawler = CourtListenerCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json = MagicMock(side_effect=ValueError("bad json"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert "error" in result.data or result.error is not None


# ===========================================================================
# 5. _parse_table_rows
# ===========================================================================


def test_parse_table_rows_tx():
    """TX HTML table is parsed into case records."""
    rows = _parse_table_rows(SAMPLE_TX_HTML, state="TX")
    assert len(rows) >= 1
    assert rows[0]["state"] == "TX"


def test_parse_table_rows_empty_html():
    """Empty HTML returns empty list."""
    rows = _parse_table_rows("<html><body></body></html>", state="TX")
    assert rows == []


# ===========================================================================
# 6. CourtStateCrawler — scrape() with mocked Playwright
# ===========================================================================


@pytest.mark.asyncio
async def test_court_state_found():
    """Mocked Playwright yields HTML with results."""
    crawler = CourtStateCrawler()

    @asynccontextmanager
    async def _mock_portal(url: str, state: str):
        yield SAMPLE_TX_HTML

    with patch.object(crawler, "_scrape_portal", side_effect=_mock_portal):
        # _scrape_portal is called for TX and NY
        with patch.object(
            crawler,
            "_scrape_portal",
            new=AsyncMock(
                return_value=[{"state": "TX", "case_number": "2023-TX-001", "parties": "SMITH"}]
            ),
        ):
            result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["case_count"] >= 1
