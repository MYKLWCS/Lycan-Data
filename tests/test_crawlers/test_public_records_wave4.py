"""
test_public_records_wave4.py — Targeted branch-coverage tests.

Crawlers covered:
  public_npi, public_nsopw, public_faa, fastpeoplesearch, truepeoplesearch

Each test class targets specific uncovered lines identified in the coverage report.
All HTTP I/O is mocked; Playwright page contexts are replaced with async stubs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def make_page_cm(html: str, title: str = "People Search"):
    """Return a context manager that yields a mock Playwright page."""
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=html)
    mock_page.title = AsyncMock(return_value=title)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    return _cm


# ===========================================================================
# public_npi.py
# Lines: 46, 68-73, 138-139, 160, 171-173
# ===========================================================================


class TestPublicNPICrawler:
    def _make(self):
        from modules.crawlers.public_npi import PublicNPICrawler

        return PublicNPICrawler()

    # line 46 — _split_name single-word returns (identifier, "")
    def test_split_name_single_word(self):
        from modules.crawlers.utils import split_name as _split_name

        first, last = _split_name("Madonna")
        assert first == "Madonna"
        assert last == ""

    # lines 68-73 — org record path in _parse_providers (authorized_official_first_name set)
    def test_parse_providers_org_record(self):
        from modules.crawlers.public_npi import _parse_providers

        data = {
            "results": [
                {
                    "number": "1234567890",
                    "basic": {
                        "authorized_official_first_name": "Jane",
                        "authorized_official_last_name": "Doe",
                        "organization_name": "Acme Health LLC",
                        "status": "A",
                        "credential": "",
                        "gender": "",
                        "enumeration_date": "2010-01-01",
                    },
                    "addresses": [
                        {
                            "address_purpose": "LOCATION",
                            "address_1": "100 Main St",
                            "city": "Houston",
                            "state": "TX",
                            "postal_code": "77001",
                        }
                    ],
                    "taxonomies": [{"desc": "Internal Medicine", "primary": True}],
                }
            ]
        }
        providers = _parse_providers(data)
        assert len(providers) == 1
        p = providers[0]
        assert p["name"] == "Jane Doe"
        assert p["org_name"] == "Acme Health LLC"
        assert p["specialty"] == "Internal Medicine"

    # lines 138-139 — org: prefix URL branch
    @pytest.mark.asyncio
    async def test_scrape_org_prefix(self):
        crawler = self._make()
        payload = {
            "result_count": 1,
            "results": [{"number": "111", "basic": {}, "addresses": [], "taxonomies": []}],
        }
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=payload))
        ):
            result = await crawler.scrape("org:Mayo Clinic")
        assert result.platform == "public_npi"
        assert isinstance(result.data.get("providers"), list)

    # line 160 — non-200 HTTP response
    # _result() stores error in data dict, not result.error
    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_503"

    # lines 171-173 — JSON parse error
    @pytest.mark.asyncio
    async def test_scrape_json_parse_error(self):
        crawler = self._make()
        bad_resp = _mock_resp(200, text="not-json")
        bad_resp.json.side_effect = ValueError("decode error")
        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "json_parse_error"

    # None response path (lines 149-157)
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # success path — providers returned
    @pytest.mark.asyncio
    async def test_scrape_success(self):
        crawler = self._make()
        payload = {
            "result_count": 1,
            "results": [
                {
                    "number": "9999999999",
                    "basic": {
                        "first_name": "Alice",
                        "last_name": "Smith",
                        "status": "A",
                        "credential": "MD",
                        "gender": "F",
                        "enumeration_date": "2005-03-15",
                    },
                    "addresses": [
                        {
                            "address_purpose": "LOCATION",
                            "address_1": "500 Oak Ave",
                            "city": "Dallas",
                            "state": "TX",
                            "postal_code": "75201",
                        }
                    ],
                    "taxonomies": [{"desc": "Cardiology", "primary": True}],
                }
            ],
        }
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=payload))
        ):
            result = await crawler.scrape("Alice Smith")
        assert result.found is True
        assert result.data["result_count"] == 1
        assert result.data["providers"][0]["npi"] == "9999999999"

    # fallback taxonomy (no primary flag)
    def test_parse_providers_fallback_taxonomy(self):
        from modules.crawlers.public_npi import _parse_providers

        data = {
            "results": [
                {
                    "number": "0001",
                    "basic": {"first_name": "Bob", "last_name": "Lee", "status": "A"},
                    "addresses": [],
                    "taxonomies": [{"desc": "Pediatrics", "primary": False}],
                }
            ]
        }
        providers = _parse_providers(data)
        assert providers[0]["specialty"] == "Pediatrics"


# ===========================================================================
# public_nsopw.py
# Lines: 47, 124, 135-137
# ===========================================================================


class TestPublicNSOPWCrawler:
    def _make(self):
        from modules.crawlers.public_nsopw import PublicNSOPWCrawler

        return PublicNSOPWCrawler()

    # line 47 — _split_name single word
    def test_split_name_single_word(self):
        from modules.crawlers.utils import split_name as _split_name

        first, last = _split_name("Prince")
        assert first == "Prince"
        assert last == ""

    # line 47 also covers — None response (lines 113-121)
    # _result() stores error in data dict
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # line 124 — non-200 status
    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        crawler = self._make()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_503"

    # lines 135-137 — JSON parse error
    @pytest.mark.asyncio
    async def test_scrape_json_parse_error(self):
        crawler = self._make()
        bad_resp = _mock_resp(200, text="<!DOCTYPE html>")
        bad_resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "post", new=AsyncMock(return_value=bad_resp)):
            result = await crawler.scrape("Jane Doe")
        assert result.found is False
        assert result.data.get("error") == "json_parse_error"

    # success path
    @pytest.mark.asyncio
    async def test_scrape_success_with_records(self):
        crawler = self._make()
        payload = {
            "TotalRecordCount": 1,
            "Records": [
                {
                    "FullName": "John Smith",
                    "Address": "123 Main St",
                    "City": "Dallas",
                    "State": "TX",
                    "DOB": "1980-01-01",
                    "Conviction": "Assault",
                }
            ],
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=payload))
        ):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.data["result_count"] == 1
        assert result.data["offenders"][0]["name"] == "John Smith"


# ===========================================================================
# public_faa.py
# Lines: 39, 59, 63, 70, 75, 107-108, 181
# ===========================================================================


class TestPublicFAACrawler:
    def _make(self):
        from modules.crawlers.public_faa import PublicFAACrawler

        return PublicFAACrawler()

    # line 39 — _split_name single-word returns ("", identifier)
    def test_split_name_single_word(self):
        from modules.crawlers.public_faa import _split_name

        first, last = _split_name("Smith")
        assert first == ""
        assert last == "Smith"

    # line 59 — table with fewer than 2 rows is skipped
    def test_parse_airmen_html_single_row_table(self):
        from modules.crawlers.public_faa import _parse_airmen_html

        html = "<table><tr><th>Certificate Number</th></tr></table>"
        result = _parse_airmen_html(html)
        assert result == []

    # line 63 — headers fewer than 3 columns
    def test_parse_airmen_html_sparse_headers(self):
        from modules.crawlers.public_faa import _parse_airmen_html

        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        result = _parse_airmen_html(html)
        assert result == []

    # line 70 — table without airmen-related keywords in headers
    def test_parse_airmen_html_non_airmen_table(self):
        from modules.crawlers.public_faa import _parse_airmen_html

        html = (
            "<table>"
            "<tr><th>Product</th><th>Price</th><th>Quantity</th></tr>"
            "<tr><td>Widget</td><td>10</td><td>5</td></tr>"
            "</table>"
        )
        result = _parse_airmen_html(html)
        assert result == []

    # line 75 — row with no <td> cells is skipped gracefully
    def test_parse_airmen_html_empty_row(self):
        from modules.crawlers.public_faa import _parse_airmen_html

        html = (
            "<table>"
            "<tr><th>Certificate Number</th><th>First Name</th><th>Last Name</th></tr>"
            "<tr></tr>"
            "</table>"
        )
        result = _parse_airmen_html(html)
        assert result == []

    # lines 107-108 — parse exception path via bs4 patch
    # BeautifulSoup is imported inside _parse_airmen_html, so patch at bs4 level
    def test_parse_airmen_html_exception(self):
        from modules.crawlers.public_faa import _parse_airmen_html

        with patch("bs4.BeautifulSoup", side_effect=RuntimeError("parse fail")):
            result = _parse_airmen_html("<html></html>")
        assert result == []

    # line 181 — GET failure: None triggers early return
    # _result() stores error inside data dict
    @pytest.mark.asyncio
    async def test_scrape_get_none(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error_get"

    @pytest.mark.asyncio
    async def test_scrape_get_non_200(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error_get"

    # POST failure path
    @pytest.mark.asyncio
    async def test_scrape_post_none(self):
        crawler = self._make()
        get_resp = _mock_resp(
            200,
            text='<input name="__VIEWSTATE" value="abc123"><input name="__VIEWSTATEGENERATOR" value="def"><input name="__EVENTVALIDATION" value="ghi">',
        )
        with (
            patch.object(crawler, "get", new=AsyncMock(return_value=get_resp)),
            patch.object(crawler, "post", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error_post"

    # success path
    @pytest.mark.asyncio
    async def test_scrape_success(self):
        crawler = self._make()
        get_resp = _mock_resp(200, text="<html><input name='__VIEWSTATE' value='vs'></html>")
        table_html = """
        <html><body>
        <table>
          <tr>
            <th>Certificate Number</th><th>First Name</th><th>Last Name</th>
            <th>City</th><th>State</th><th>Certificates</th>
          </tr>
          <tr>
            <td>P123456</td><td>John</td><td>Smith</td>
            <td>Austin</td><td>TX</td><td>Private Pilot, Instrument</td>
          </tr>
        </table>
        </body></html>
        """
        post_resp = _mock_resp(200, text=table_html)
        with (
            patch.object(crawler, "get", new=AsyncMock(return_value=get_resp)),
            patch.object(crawler, "post", new=AsyncMock(return_value=post_resp)),
        ):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.data["result_count"] == 1
        assert result.data["pilots"][0]["certificate_number"] == "P123456"


# ===========================================================================
# fastpeoplesearch.py
# Lines: 36, 114, 123, 126-128
# ===========================================================================


class TestFastPeopleSearchCrawler:
    def _make(self):
        from modules.crawlers.fastpeoplesearch import FastPeopleSearchCrawler

        return FastPeopleSearchCrawler()

    # line 36 — no last name: name_path = first_slug only
    @pytest.mark.asyncio
    async def test_scrape_first_name_only(self):
        crawler = self._make()
        html = "<html><body><p>No results found.</p></body></html>"
        with patch.object(crawler, "page", make_page_cm(html)):
            result = await crawler.scrape("Madonna")
        assert result.found is True
        assert result.data["results"] == []

    # line 114 — phone_els found (class containing "phone")
    def test_extract_fps_card_phone_els(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.fastpeoplesearch import _extract_fps_card

        html = """
        <div class="card-block">
          <h2>Alice Tester</h2>
          <span class="phone-number">(512) 555-0100</span>
          <span class="phone-number">(512) 555-0101</span>
        </div>
        """
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_fps_card(card)
        assert result is not None
        assert "(512) 555-0100" in result["phone_numbers"]

    # line 123 — full_name empty → returns None
    def test_extract_fps_card_no_name_returns_none(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.fastpeoplesearch import _extract_fps_card

        html = "<div class='card-block'><span>No name here</span></div>"
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_fps_card(card)
        assert result is None

    # lines 126-128 — exception path returns None
    def test_extract_fps_card_exception_returns_none(self):
        from modules.crawlers.fastpeoplesearch import _extract_fps_card

        bad_card = MagicMock()
        bad_card.find.side_effect = RuntimeError("boom")
        result = _extract_fps_card(bad_card)
        assert result is None

    # city+state URL branch (lines 38-41)
    @pytest.mark.asyncio
    async def test_scrape_with_city_state(self):
        crawler = self._make()
        html = """
        <html><body>
          <div class="card-block">
            <h2>Jane Doe</h2>
            <span>Age 33</span>
          </div>
        </body></html>
        """
        with patch.object(crawler, "page", make_page_cm(html)):
            result = await crawler.scrape("Jane Doe|Dallas,TX")
        assert result.found is True


# ===========================================================================
# truepeoplesearch.py
# Lines: 95, 114, 121, 128, 133, 136-138
# ===========================================================================


class TestTruePeopleSearchCrawler:
    def _make(self):
        from modules.crawlers.truepeoplesearch import TruePeopleSearchCrawler

        return TruePeopleSearchCrawler()

    # line 95 — name_el falls back to h2/h3 (no "name" class)
    def test_extract_tps_card_fallback_name_el(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.truepeoplesearch import _extract_tps_card

        html = "<div class='card'><h2>Bob Smith</h2><span>Age 40</span></div>"
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_tps_card(card)
        assert result is not None
        assert result["full_name"] == "Bob Smith"

    # line 114 — phone_els branch (class containing "phone")
    def test_extract_tps_card_phone_els(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.truepeoplesearch import _extract_tps_card

        html = """
        <div class='card'>
          <h2>Carol Jones</h2>
          <span class="phone">(214) 555-0199</span>
        </div>
        """
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_tps_card(card)
        assert result is not None
        assert any("555-0199" in p for p in result["phone_numbers"])

    # line 121 — relatives el found
    def test_extract_tps_card_relatives(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.truepeoplesearch import _extract_tps_card

        html = """
        <div class='card'>
          <h2>Dave Brown</h2>
          <div class="relative-list">
            <a href="#">Mary Brown</a>
            <a href="#">Tom Brown</a>
          </div>
        </div>
        """
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_tps_card(card)
        assert result is not None
        assert "Mary Brown" in result["relatives"]

    # line 128 — associates el found
    def test_extract_tps_card_associates(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.truepeoplesearch import _extract_tps_card

        html = """
        <div class='card'>
          <h2>Eve Green</h2>
          <div class="associate-list">
            <a href="#">Frank Green</a>
          </div>
        </div>
        """
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_tps_card(card)
        assert result is not None
        assert "Frank Green" in result["associates"]

    # line 133 — no full_name → returns None
    def test_extract_tps_card_no_name_returns_none(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.truepeoplesearch import _extract_tps_card

        html = "<div class='card'><span>Age 30</span></div>"
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_tps_card(card)
        assert result is None

    # lines 136-138 — exception path
    def test_extract_tps_card_exception_returns_none(self):
        from modules.crawlers.truepeoplesearch import _extract_tps_card

        bad_card = MagicMock()
        bad_card.find.side_effect = RuntimeError("kaboom")
        result = _extract_tps_card(bad_card)
        assert result is None

    # scraper — No Records Found path (line 65)
    @pytest.mark.asyncio
    async def test_scrape_no_records(self):
        crawler = self._make()
        html = "<html><body><p>No Records Found for this search.</p></body></html>"
        with patch.object(crawler, "page", make_page_cm(html)):
            result = await crawler.scrape("Xyz Notreal")
        assert result.found is False
        assert result.data["results"] == []

    # scraper — successful parse with multiple cards (line 95 via scrape)
    @pytest.mark.asyncio
    async def test_scrape_success(self):
        crawler = self._make()
        html = """
        <html><body>
          <div class="card">
            <h2 class="name">Robert Johnson</h2>
            <span>Age 50</span>
          </div>
        </body></html>
        """
        with patch.object(crawler, "page", make_page_cm(html)):
            result = await crawler.scrape("Robert Johnson")
        assert result.found is True
        assert result.data["result_count"] >= 1
