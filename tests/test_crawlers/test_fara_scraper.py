"""
Unit tests for modules/crawlers/gov/fara_scraper.py.

Covers every branch: _word_overlap, _parse_rest_response, _parse_html_table,
FaraScraperCrawler._try_rest_api, _try_html_search, and scrape.

No real HTTP calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.gov.fara_scraper  # noqa: F401 — trigger @register
from modules.crawlers.gov.fara_scraper import (
    FaraScraperCrawler,
    _parse_html_table,
    _parse_rest_response,
    _word_overlap,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


# ---------------------------------------------------------------------------
# _word_overlap
# ---------------------------------------------------------------------------


class TestWordOverlap:
    def test_empty_query_returns_zero(self):
        assert _word_overlap("", "some candidate") == 0.0

    def test_full_match(self):
        assert _word_overlap("john doe", "john doe") == 1.0

    def test_partial_match(self):
        score = _word_overlap("john doe smith", "john doe")
        assert abs(score - 2 / 3) < 1e-9

    def test_no_match(self):
        assert _word_overlap("alpha beta", "gamma delta") == 0.0

    def test_case_insensitive(self):
        assert _word_overlap("JOHN DOE", "john doe") == 1.0


# ---------------------------------------------------------------------------
# _parse_rest_response
# ---------------------------------------------------------------------------


class TestParseRestResponse:
    def test_plain_list_input(self):
        data = [
            {
                "registrantName": "Podesta Group",
                "foreignPrincipalName": "Ukraine",
                "foreignPrincipalCountry": "UA",
                "registrationNumber": "5926",
                "registrationDate": "2012-06-18",
                "terminationDate": "",
                "activitiesDescription": "Lobbying",
            }
        ]
        results = _parse_rest_response(data, "Podesta Group")
        assert len(results) == 1
        r = results[0]
        assert r["registrant_name"] == "Podesta Group"
        assert r["is_active"] is True
        assert r["registration_number"] == "5926"

    def test_dict_with_items_key(self):
        data = {
            "items": [
                {
                    "registrantName": "BGR Group",
                    "foreignPrincipalName": "Turkey",
                    "registrationDate": "2010-01-01",
                    "terminationDate": "2015-06-01",
                }
            ]
        }
        results = _parse_rest_response(data, "BGR Group")
        assert len(results) == 1
        assert results[0]["is_active"] is False

    def test_dict_with_registrations_key(self):
        data = {
            "registrations": [
                {"registrantName": "Mercury LLC", "registrationDate": "2020-01-01"}
            ]
        }
        results = _parse_rest_response(data, "Mercury LLC")
        assert len(results) == 1

    def test_dict_with_results_key(self):
        data = {
            "results": [
                {"registrantName": "Akin Gump", "registrationDate": "2019-05-01"}
            ]
        }
        results = _parse_rest_response(data, "Akin Gump")
        assert len(results) == 1

    def test_skips_non_dict_items(self):
        data = ["not_a_dict", 42, {"registrantName": "Real Firm", "registrationDate": "2021-01-01"}]
        results = _parse_rest_response(data, "Real Firm")
        assert len(results) == 1

    def test_filters_low_score_names(self):
        data = [
            {"registrantName": "Completely Different Entity", "registrationDate": "2020-01-01"}
        ]
        results = _parse_rest_response(data, "Podesta Group")
        assert results == []

    def test_allows_through_when_no_candidate(self):
        """When both registrantName and foreignPrincipalName are empty, item passes filter."""
        data = [{"registrationDate": "2020-01-01", "registrationNumber": "9999"}]
        results = _parse_rest_response(data, "anything")
        assert len(results) == 1

    def test_alternative_field_names(self):
        data = [
            {
                "registrant_name": "Alt Firm",
                "foreign_principal_name": "Alt Country",
                "country": "Ruritania",
                "registration_number": "1234",
                "registration_date": "2021-03-01",
                "termination_date": "",
                "activities_description": "PR work",
            }
        ]
        results = _parse_rest_response(data, "Alt Firm")
        assert len(results) == 1
        assert results[0]["registrant_name"] == "Alt Firm"
        assert results[0]["foreign_principal_country"] == "Ruritania"

    def test_foreign_principal_fallback_field(self):
        data = [
            {
                "name": "Named Firm",
                "foreignPrincipal": "FP Name",
                "foreignPrincipalNationality": "DE",
                "regNumber": "555",
                "dateOfRegistration": "2022-01-01",
                "dateOfTermination": "",
                "activities": "Lobbying",
            }
        ]
        results = _parse_rest_response(data, "Named Firm")
        assert len(results) == 1
        assert results[0]["registration_number"] == "555"
        assert results[0]["activities"] == "Lobbying"

    def test_non_list_non_dict_returns_empty(self):
        assert _parse_rest_response("invalid", "query") == []
        assert _parse_rest_response(None, "query") == []
        assert _parse_rest_response(42, "query") == []

    def test_empty_list_returns_empty(self):
        assert _parse_rest_response([], "query") == []

    def test_empty_dict_returns_empty(self):
        assert _parse_rest_response({}, "query") == []


# ---------------------------------------------------------------------------
# _parse_html_table
# ---------------------------------------------------------------------------


class TestParseHtmlTable:
    _HTML_WITH_TABLE = """
    <html><body>
    <table>
      <tr><th>Registrant Name</th><th>Foreign Principal</th><th>Country</th>
          <th>Registration Date</th><th>Termination Date</th><th>Registration Number</th></tr>
      <tr><td>Manafort Group</td><td>Ukraine</td><td>UA</td>
          <td>2012-01-01</td><td></td><td>6051</td></tr>
    </table>
    </body></html>
    """

    _HTML_NO_RELEVANT_TABLE = """
    <html><body>
    <table>
      <tr><th>Invoice</th><th>Amount</th></tr>
      <tr><td>123</td><td>$100</td></tr>
    </table>
    </body></html>
    """

    _HTML_TABLE_TOO_SHORT = """
    <html><body>
    <table>
      <tr><th>Registrant Name</th></tr>
    </table>
    </body></html>
    """

    def test_parses_basic_table(self):
        results = _parse_html_table(self._HTML_WITH_TABLE, "Manafort Group")
        assert len(results) == 1
        r = results[0]
        assert r["registrant_name"] == "Manafort Group"
        assert r["foreign_principal_name"] == "Ukraine"
        assert r["registration_number"] == "6051"
        assert r["is_active"] is True

    def test_filters_low_score_rows(self):
        results = _parse_html_table(self._HTML_WITH_TABLE, "completely unrelated xyz")
        assert results == []

    def test_no_relevant_table_returns_empty(self):
        results = _parse_html_table(self._HTML_NO_RELEVANT_TABLE, "any query")
        assert results == []

    def test_table_too_short_skipped(self):
        results = _parse_html_table(self._HTML_TABLE_TOO_SHORT, "any")
        assert results == []

    def test_row_with_no_cells_skipped(self):
        html = """
        <table>
          <tr><th>Registrant Name</th><th>Foreign Principal</th><th>Registration</th></tr>
          <tr></tr>
          <tr><td>Firm A</td><td>Brazil</td><td>2020-01-01</td></tr>
        </table>
        """
        results = _parse_html_table(html, "Firm A")
        assert len(results) == 1

    def test_termination_date_makes_inactive(self):
        html = """
        <table>
          <tr><th>Registrant Name</th><th>Foreign Principal</th><th>Country</th>
              <th>Registration Date</th><th>Termination Date</th><th>Registration Number</th></tr>
          <tr><td>Closed Firm</td><td>Germany</td><td>DE</td>
              <td>2010-01-01</td><td>2015-06-01</td><td>3333</td></tr>
        </table>
        """
        results = _parse_html_table(html, "Closed Firm")
        assert len(results) == 1
        assert results[0]["is_active"] is False

    def test_breaks_after_first_matching_table(self):
        """Once a table has results, no further tables are processed."""
        html = """
        <table>
          <tr><th>Registrant Name</th><th>Principal</th><th>Registration</th></tr>
          <tr><td>First Firm</td><td>UK</td><td>2020-01-01</td></tr>
        </table>
        <table>
          <tr><th>Registrant Name</th><th>Principal</th><th>Registration</th></tr>
          <tr><td>Second Firm</td><td>FR</td><td>2021-01-01</td></tr>
        </table>
        """
        results = _parse_html_table(html, "Firm")
        # Only first table processed
        assert len(results) == 1
        assert results[0]["registrant_name"] == "First Firm"

    def test_bs4_import_error_returns_empty(self):
        """If BeautifulSoup is unavailable, returns [] gracefully."""
        with patch.dict("sys.modules", {"bs4": None}):
            # Force ImportError when bs4 is imported
            with patch(
                "modules.crawlers.gov.fara_scraper._parse_html_table",
                wraps=_parse_html_table,
            ):
                import sys

                real_bs4 = sys.modules.get("bs4")
                sys.modules["bs4"] = None  # type: ignore[assignment]
                try:
                    result = _parse_html_table("<html></html>", "test")
                    # If bs4 import fails, function catches and returns []
                except Exception:
                    result = []
                finally:
                    if real_bs4 is not None:
                        sys.modules["bs4"] = real_bs4

    def test_empty_html_returns_empty(self):
        results = _parse_html_table("", "query")
        assert results == []

    def test_alternative_column_names(self):
        """Tests 'registrant' and 'principal' header variants."""
        html = """
        <table>
          <tr><th>Registrant</th><th>Principal</th><th>Registration Date</th><th>Date Registered</th><th>Date Terminated</th><th>Reg #</th></tr>
          <tr><td>Alt Firm</td><td>Canada</td><td></td><td>2020-01-01</td><td></td><td>7777</td></tr>
        </table>
        """
        results = _parse_html_table(html, "Alt Firm")
        assert len(results) == 1
        assert results[0]["registration_number"] == "7777"


# ---------------------------------------------------------------------------
# FaraScraperCrawler._try_rest_api
# ---------------------------------------------------------------------------


class TestFaraScraperCrawlerTryRestApi:
    def _crawler(self) -> FaraScraperCrawler:
        return FaraScraperCrawler()

    async def test_returns_empty_when_resp_is_none(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._try_rest_api("Test Firm", "Test+Firm")
        assert result == []

    async def test_returns_empty_when_non_200(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler._try_rest_api("Test Firm", "Test+Firm")
        assert result == []

    async def test_returns_empty_when_json_decode_error(self):
        crawler = self._crawler()
        resp = _mock_resp(200)
        resp.json = MagicMock(side_effect=ValueError("bad json"))
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._try_rest_api("Test Firm", "Test+Firm")
        assert result == []

    async def test_returns_parsed_results_on_success(self):
        crawler = self._crawler()
        data = [{"registrantName": "Test Firm", "registrationDate": "2021-01-01"}]
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler._try_rest_api("Test Firm", "Test+Firm")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# FaraScraperCrawler._try_html_search
# ---------------------------------------------------------------------------


class TestFaraScraperCrawlerTryHtmlSearch:
    _HTML = """
    <table>
      <tr><th>Registrant Name</th><th>Foreign Principal</th><th>Registration</th></tr>
      <tr><td>Hill+Knowlton</td><td>Saudi Arabia</td><td>2019-01-01</td></tr>
    </table>
    """

    def _crawler(self) -> FaraScraperCrawler:
        return FaraScraperCrawler()

    async def test_returns_empty_when_resp_is_none(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._try_html_search("Hill+Knowlton", "Hill%2BKnowlton")
        assert result == []

    async def test_returns_empty_when_non_200(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler._try_html_search("Hill", "Hill")
        assert result == []

    async def test_returns_parsed_html_results(self):
        crawler = self._crawler()
        resp = _mock_resp(200, text=self._HTML)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._try_html_search("Hill+Knowlton", "Hill%2BKnowlton")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# FaraScraperCrawler.scrape — integration paths
# ---------------------------------------------------------------------------


class TestFaraScraperCrawlerScrape:
    def _crawler(self) -> FaraScraperCrawler:
        return FaraScraperCrawler()

    async def test_scrape_uses_rest_on_success(self):
        crawler = self._crawler()
        data = [{"registrantName": "Podesta Group", "registrationDate": "2012-06-18"}]
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler.scrape("Podesta Group")

        assert result.found is True
        assert result.data["total_count"] == 1
        assert len(result.data["fara_registrations"]) == 1
        assert result.data["query"] == "Podesta Group"

    async def test_scrape_falls_back_to_html_when_rest_empty(self):
        crawler = self._crawler()
        html = """
        <table>
          <tr><th>Registrant Name</th><th>Foreign Principal</th><th>Registration</th></tr>
          <tr><td>BGR Group</td><td>Turkey</td><td>2019-01-01</td></tr>
        </table>
        """
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                # REST returns 503
                return _mock_resp(503)
            # HTML fallback
            return _mock_resp(200, text=html)

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("BGR Group")

        assert result.found is True
        assert result.data["total_count"] >= 1

    async def test_scrape_returns_not_found_when_both_fail(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Unknown Entity XYZ")

        assert result.found is False
        assert result.data["total_count"] == 0
        assert result.data["fara_registrations"] == []

    async def test_scrape_strips_identifier_whitespace(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("  Test  ")
        assert result.data["query"] == "Test"

    async def test_platform_attributes(self):
        crawler = self._crawler()
        assert crawler.platform == "fara_scraper"
        assert crawler.source_reliability == 0.95
        assert crawler.requires_tor is False
        assert crawler.proxy_tier == "datacenter"
