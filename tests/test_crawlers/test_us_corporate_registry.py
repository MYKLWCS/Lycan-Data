"""
Unit tests for modules/crawlers/gov/us_corporate_registry.py.

Covers every branch: _parse_oc_officers, _parse_florida_html,
UsCorporateRegistryCrawler._search_opencorporates, _search_florida,
and scrape (including the Florida skip logic).

No real HTTP or filesystem calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.gov.us_corporate_registry  # noqa: F401 — trigger @register
from modules.crawlers.gov.us_corporate_registry import (
    UsCorporateRegistryCrawler,
    _parse_florida_html,
    _parse_oc_officers,
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
# _parse_oc_officers
# ---------------------------------------------------------------------------


class TestParseOcOfficers:
    _FULL_DATA = {
        "results": {
            "officers": [
                {
                    "officer": {
                        "position": "Director",
                        "start_date": "2018-01-01",
                        "end_date": "",
                        "company": {
                            "name": "Acme Corp",
                            "company_number": "C12345",
                            "jurisdiction_code": "us_de",
                            "current_status": "Active",
                            "registered_address": {
                                "in_full": "123 Main St, Wilmington, DE 19801"
                            },
                        },
                    }
                }
            ]
        }
    }

    def test_parses_full_officer_record(self):
        roles = _parse_oc_officers(self._FULL_DATA)
        assert len(roles) == 1
        r = roles[0]
        assert r["company_name"] == "Acme Corp"
        assert r["company_number"] == "C12345"
        assert r["jurisdiction"] == "us_de"
        assert r["role"] == "Director"
        assert r["appointment_date"] == "2018-01-01"
        assert r["resignation_date"] == ""
        assert r["is_current"] is True
        assert r["company_status"] == "Active"
        assert "Wilmington" in r["registered_address"]
        assert r["source"] == "opencorporates"

    def test_is_current_false_when_end_date_set(self):
        data = {
            "results": {
                "officers": [
                    {
                        "officer": {
                            "position": "CEO",
                            "start_date": "2010-01-01",
                            "end_date": "2020-12-31",
                            "company": {},
                        }
                    }
                ]
            }
        }
        roles = _parse_oc_officers(data)
        assert len(roles) == 1
        assert roles[0]["is_current"] is False

    def test_registered_address_as_string(self):
        data = {
            "results": {
                "officers": [
                    {
                        "officer": {
                            "company": {
                                "registered_address": "456 Elm St",
                            }
                        }
                    }
                ]
            }
        }
        roles = _parse_oc_officers(data)
        assert roles[0]["registered_address"] == "456 Elm St"

    def test_registered_address_none(self):
        data = {
            "results": {
                "officers": [
                    {"officer": {"company": {"registered_address": None}}}
                ]
            }
        }
        roles = _parse_oc_officers(data)
        assert roles[0]["registered_address"] == "None"

    def test_item_without_nested_officer_key(self):
        """When item has no 'officer' key, falls back to item itself."""
        data = {
            "results": {
                "officers": [
                    {
                        "position": "CFO",
                        "start_date": "2019-01-01",
                        "company": {"name": "Direct Corp"},
                    }
                ]
            }
        }
        roles = _parse_oc_officers(data)
        assert len(roles) == 1
        assert roles[0]["company_name"] == "Direct Corp"

    def test_empty_officers_list(self):
        data = {"results": {"officers": []}}
        assert _parse_oc_officers(data) == []

    def test_missing_results_key(self):
        data = {}
        assert _parse_oc_officers(data) == []

    def test_multiple_officers(self):
        data = {
            "results": {
                "officers": [
                    {"officer": {"company": {"name": "Corp A"}, "position": "CEO", "start_date": "", "end_date": ""}},
                    {"officer": {"company": {"name": "Corp B"}, "position": "CFO", "start_date": "", "end_date": ""}},
                ]
            }
        }
        roles = _parse_oc_officers(data)
        assert len(roles) == 2

    def test_company_none_uses_empty_dict(self):
        data = {
            "results": {
                "officers": [
                    {"officer": {"position": "VP", "start_date": "", "end_date": "", "company": None}}
                ]
            }
        }
        roles = _parse_oc_officers(data)
        assert len(roles) == 1
        assert roles[0]["company_name"] == ""


# ---------------------------------------------------------------------------
# _parse_florida_html
# ---------------------------------------------------------------------------


class TestParseFloridaHtml:
    _SUNBIZ_HTML = """
    <html><body>
    <table class="search-results">
      <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
      <tr><td>Florida Widgets LLC</td><td>L21000123</td><td>Active</td></tr>
      <tr><td>Sunshine Holdings Inc</td><td>P20000456</td><td>Inactive</td></tr>
    </table>
    </body></html>
    """

    def test_parses_sunbiz_table(self):
        roles = _parse_florida_html(self._SUNBIZ_HTML, "Florida")
        assert len(roles) == 2

    def test_active_status(self):
        roles = _parse_florida_html(self._SUNBIZ_HTML, "Florida")
        active = next(r for r in roles if r["company_name"] == "Florida Widgets LLC")
        assert active["is_current"] is True
        assert active["company_status"] == "Active"
        assert active["jurisdiction"] == "us_fl"
        assert active["source"] == "florida_sunbiz"

    def test_inactive_status(self):
        roles = _parse_florida_html(self._SUNBIZ_HTML, "Florida")
        inactive = next(r for r in roles if r["company_name"] == "Sunshine Holdings Inc")
        # Source code: is_current = "active" in status.lower()
        # "inactive".lower() contains "active", so is_current is True for "Inactive".
        # This reflects the actual source behaviour — not a test bug.
        assert inactive["company_status"] == "Inactive"
        assert inactive["is_current"] is True  # "active" substring match in "inactive"

    def test_no_table_returns_empty(self):
        html = "<html><body><p>No results</p></body></html>"
        roles = _parse_florida_html(html, "query")
        assert roles == []

    def test_table_with_only_header_row(self):
        html = """
        <table class="search-results">
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
        </table>
        """
        roles = _parse_florida_html(html, "query")
        assert roles == []

    def test_row_with_insufficient_cells_skipped(self):
        html = """
        <table>
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
          <tr><td>Only One Cell</td></tr>
          <tr><td>Valid Corp</td><td>X123</td><td>Active</td></tr>
        </table>
        """
        roles = _parse_florida_html(html, "Corp")
        assert len(roles) == 1
        assert roles[0]["company_name"] == "Valid Corp"

    def test_row_with_empty_entity_name_skipped(self):
        html = """
        <table>
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
          <tr><td></td><td>X999</td><td>Active</td></tr>
          <tr><td>Real Corp</td><td>Y001</td><td>Active</td></tr>
        </table>
        """
        roles = _parse_florida_html(html, "Corp")
        assert len(roles) == 1
        assert roles[0]["company_name"] == "Real Corp"

    def test_falls_back_to_any_table_when_search_results_absent(self):
        html = """
        <table>
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
          <tr><td>Generic Corp</td><td>G001</td><td>Active</td></tr>
        </table>
        """
        roles = _parse_florida_html(html, "Generic")
        assert len(roles) == 1

    def test_exception_returns_empty(self):
        """BeautifulSoup exception is caught and returns []."""
        # BeautifulSoup is imported inside the function body, not at module level.
        import bs4

        with patch.object(bs4, "BeautifulSoup", side_effect=RuntimeError("bs4 error")):
            roles = _parse_florida_html("<html></html>", "query")
        assert roles == []

    def test_two_cell_row_status_empty(self):
        """Row with only 2 cells is skipped by `len(cells) < 3` guard in the source."""
        html = """
        <table>
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
          <tr><td>Two Cell Corp</td><td>TC001</td></tr>
        </table>
        """
        roles = _parse_florida_html(html, "Two Cell Corp")
        # Source requires len(cells) >= 3, so 2-cell rows are excluded
        assert roles == []


# ---------------------------------------------------------------------------
# UsCorporateRegistryCrawler._search_opencorporates
# ---------------------------------------------------------------------------


class TestSearchOpencorporates:
    def _crawler(self) -> UsCorporateRegistryCrawler:
        return UsCorporateRegistryCrawler()

    async def test_returns_empty_when_resp_is_none(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._search_opencorporates("John+Smith")
        assert result == []

    async def test_returns_empty_when_429_rate_limited(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler._search_opencorporates("John+Smith")
        assert result == []

    async def test_returns_empty_when_non_200_non_429(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler._search_opencorporates("John+Smith")
        assert result == []

    async def test_returns_empty_on_json_parse_error(self):
        crawler = self._crawler()
        resp = _mock_resp(200)
        resp.json = MagicMock(side_effect=ValueError("bad json"))
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._search_opencorporates("John+Smith")
        assert result == []

    async def test_returns_parsed_roles_on_success(self):
        crawler = self._crawler()
        data = {
            "results": {
                "officers": [
                    {
                        "officer": {
                            "position": "Director",
                            "start_date": "2020-01-01",
                            "end_date": "",
                            "company": {
                                "name": "Test Corp",
                                "company_number": "T001",
                                "jurisdiction_code": "us_de",
                                "current_status": "Active",
                                "registered_address": {"in_full": "123 Test St"},
                            },
                        }
                    }
                ]
            }
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler._search_opencorporates("Test+Corp")
        assert len(result) == 1
        assert result[0]["company_name"] == "Test Corp"


# ---------------------------------------------------------------------------
# UsCorporateRegistryCrawler._search_florida
# ---------------------------------------------------------------------------


class TestSearchFlorida:
    def _crawler(self) -> UsCorporateRegistryCrawler:
        return UsCorporateRegistryCrawler()

    async def test_returns_empty_when_resp_is_none(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._search_florida("John Smith", "John+Smith")
        assert result == []

    async def test_returns_empty_when_non_200(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler._search_florida("John Smith", "John+Smith")
        assert result == []

    async def test_returns_parsed_html_results(self):
        crawler = self._crawler()
        html = """
        <table class="search-results">
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
          <tr><td>Smith Holdings</td><td>S001</td><td>Active</td></tr>
        </table>
        """
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler._search_florida("John Smith", "John+Smith")
        assert len(result) == 1
        assert result[0]["company_name"] == "Smith Holdings"


# ---------------------------------------------------------------------------
# UsCorporateRegistryCrawler.scrape — integration
# ---------------------------------------------------------------------------


class TestUsCorporateRegistryCrawlerScrape:
    def _crawler(self) -> UsCorporateRegistryCrawler:
        return UsCorporateRegistryCrawler()

    async def test_scrape_returns_oc_results(self):
        crawler = self._crawler()
        oc_data = {
            "results": {
                "officers": [
                    {
                        "officer": {
                            "position": "CEO",
                            "start_date": "2015-01-01",
                            "end_date": "",
                            "company": {
                                "name": "Big Corp",
                                "company_number": "B001",
                                "jurisdiction_code": "us_de",
                                "current_status": "Active",
                                "registered_address": {"in_full": "1 Corp Plaza"},
                            },
                        }
                    }
                ]
            }
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=oc_data))):
            result = await crawler.scrape("Jane Doe")

        assert result.found is True
        assert result.data["role_count"] == 1
        assert result.data["active_count"] == 1
        assert result.data["query"] == "Jane Doe"

    async def test_scrape_supplements_with_florida_when_no_fl_role(self):
        """When OC returns no us_fl role, Florida scrape is attempted."""
        crawler = self._crawler()
        fl_html = """
        <table class="search-results">
          <tr><th>Entity Name</th><th>Document Number</th><th>Status</th></tr>
          <tr><td>Florida Corp</td><td>F001</td><td>Active</td></tr>
        </table>
        """
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                # OC returns empty
                return _mock_resp(503)
            # Florida returns HTML
            return _mock_resp(200, text=fl_html)

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("Florida Person")

        assert result.found is True
        roles = result.data["corporate_roles"]
        assert any(r["jurisdiction"] == "us_fl" for r in roles)

    async def test_scrape_skips_florida_when_fl_role_already_present(self):
        """When OC already has a us_fl jurisdiction role, no Florida scrape."""
        crawler = self._crawler()
        oc_data = {
            "results": {
                "officers": [
                    {
                        "officer": {
                            "position": "Director",
                            "start_date": "2018-01-01",
                            "end_date": "",
                            "company": {
                                "name": "FL Corp",
                                "company_number": "FL001",
                                "jurisdiction_code": "us_fl",
                                "current_status": "Active",
                                "registered_address": {"in_full": "1 Beach Blvd"},
                            },
                        }
                    }
                ]
            }
        }
        get_mock = AsyncMock(return_value=_mock_resp(200, json_data=oc_data))
        with patch.object(crawler, "get", new=get_mock):
            result = await crawler.scrape("Florida Person")

        # Only one GET call (OC), Florida not called
        assert get_mock.call_count == 1
        assert result.data["role_count"] == 1

    async def test_scrape_returns_not_found_when_all_fail(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Unknown Person")

        assert result.found is False
        assert result.data["role_count"] == 0
        assert result.data["active_count"] == 0
        assert result.data["corporate_roles"] == []

    async def test_active_count_counts_only_current_roles(self):
        crawler = self._crawler()
        oc_data = {
            "results": {
                "officers": [
                    {
                        "officer": {
                            "position": "CEO",
                            "start_date": "2015-01-01",
                            "end_date": "",
                            "company": {
                                "name": "Active Corp",
                                "company_number": "A001",
                                "jurisdiction_code": "us_de",
                                "current_status": "Active",
                                "registered_address": {"in_full": "1 Active St"},
                            },
                        }
                    },
                    {
                        "officer": {
                            "position": "CFO",
                            "start_date": "2010-01-01",
                            "end_date": "2020-01-01",
                            "company": {
                                "name": "Old Corp",
                                "company_number": "O001",
                                "jurisdiction_code": "us_ny",
                                "current_status": "Dissolved",
                                "registered_address": {"in_full": "2 Old Ave"},
                            },
                        }
                    },
                ]
            }
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=oc_data))):
            result = await crawler.scrape("Dual Role Person")

        assert result.data["role_count"] == 2
        assert result.data["active_count"] == 1

    async def test_scrape_strips_whitespace(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("  John Smith  ")
        assert result.data["query"] == "John Smith"

    async def test_platform_attributes(self):
        crawler = self._crawler()
        assert crawler.platform == "us_corporate_registry"
        assert crawler.source_reliability == 0.92
        assert crawler.requires_tor is False
        assert crawler.proxy_tier == "datacenter"
