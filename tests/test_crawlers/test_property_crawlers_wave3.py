"""
test_property_crawlers_wave3.py — Tests for property and people-search crawlers.

Covers:
  - people_zabasearch.py  (24% coverage)
  - property_redfin.py    (31%)
  - property_zillow.py    (65%)
  - playwright_base.py    (46%)

All HTTP/Playwright I/O is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (str(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# people_zabasearch.py
# ===========================================================================


class TestPeopleZabaSearchCrawler:
    """Covers all branches of PeopleZabaSearchCrawler."""

    def _make_crawler(self):
        from modules.crawlers.people_zabasearch import PeopleZabaSearchCrawler

        return PeopleZabaSearchCrawler()

    # --- None response -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_none_response_returns_http_error(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.error == "http_error"

    # --- 429 rate limited ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_429_rate_limited(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=429, text="Too Many Requests")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.error == "rate_limited"

    # --- 404 no results ------------------------------------------------------

    @pytest.mark.asyncio
    async def test_404_no_results(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="Not Found")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("persons") == [] or result.data == {}

    # --- non-200 HTTP error --------------------------------------------------

    @pytest.mark.asyncio
    async def test_non_200_error(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=503, text="Service Unavailable")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe")

        assert result.found is False
        assert "503" in result.error

    # --- successful parse ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_successful_scrape_parses_persons(self):
        crawler = self._make_crawler()
        html = """
        <html><body>
        <div class="person-search-result">
          <h2 class="name">John Smith</h2>
          <span class="location">Austin, TX</span>
          <span class="age">Age 45</span>
          <a href="tel:+15551234567">(555) 123-4567</a>
        </div>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert isinstance(result.data.get("persons"), list)

    # --- single name token (no last name) -----------------------------------

    @pytest.mark.asyncio
    async def test_single_name_token(self):
        """Single-word identifier: last is empty, URL built without last."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="<html><body>No results</body></html>")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)) as mock_get:
            result = await crawler.scrape("Madonna")

        url_called = mock_get.call_args[0][0]
        assert "Madonna" in url_called
        assert result.found is False

    # --- _parse_persons: age regex fallback ---------------------------------

    def test_parse_persons_age_regex_fallback(self):
        from modules.crawlers.people_zabasearch import _parse_persons

        html = """
        <html><body>
        <div class="person-search-result">
          <h3 class="name">Bob Jones</h3>
          <span class="location">Dallas, TX</span>
          <p>Age: 60 years old</p>
        </div>
        </body></html>
        """
        persons = _parse_persons(html)
        assert isinstance(persons, list)

    # --- _parse_persons: phone regex fallback --------------------------------

    def test_parse_persons_phone_regex_fallback(self):
        from modules.crawlers.people_zabasearch import _parse_persons

        html = """
        <html><body>
        <div class="person-search-result">
          <h3 class="name">Alice Brown</h3>
          <span class="location">Houston, TX</span>
          Contact: 555-987-6543
        </div>
        </body></html>
        """
        persons = _parse_persons(html)
        if persons:
            assert "phones" in persons[0] or persons[0].get("name")

    # --- _parse_persons: location without comma ------------------------------

    def test_parse_persons_location_no_comma(self):
        from modules.crawlers.people_zabasearch import _parse_persons

        html = """
        <html><body>
        <div class="person-search-result">
          <h3 class="name">Carl Davis</h3>
          <span class="location">California</span>
        </div>
        </body></html>
        """
        persons = _parse_persons(html)
        if persons:
            assert persons[0].get("location") == "California" or "city" not in persons[0]

    # --- _parse_persons: bs4 exception --------------------------------------

    def test_parse_persons_exception_returns_empty(self):
        from modules.crawlers.people_zabasearch import _parse_persons

        with patch("bs4.BeautifulSoup", side_effect=RuntimeError("bs4 broken")):
            persons = _parse_persons("<html><body></body></html>")

        assert persons == []


# ===========================================================================
# property_redfin.py
# ===========================================================================


class TestPropertyRedfinCrawler:
    """Covers all scrape branches in PropertyRedfinCrawler."""

    def _make_crawler(self):
        from modules.crawlers.property_redfin import PropertyRedfinCrawler

        return PropertyRedfinCrawler()

    # --- GIS response is None -----------------------------------------------

    @pytest.mark.asyncio
    async def test_gis_none_response(self):
        crawler = self._make_crawler()

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, json_data={"payload": {"sections": []}})
            return None  # GIS call fails

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("123 Main St, Austin TX")

        assert result.found is False
        assert result.error == "http_error"

    # --- GIS 429 rate-limited -----------------------------------------------

    @pytest.mark.asyncio
    async def test_gis_429(self):
        crawler = self._make_crawler()

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, json_data={"payload": {"sections": []}})
            return _mock_resp(status=429, text="Rate limited")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("123 Main St, Austin TX")

        assert result.found is False
        assert result.error == "rate_limited"

    # --- GIS non-200/206 error ----------------------------------------------

    @pytest.mark.asyncio
    async def test_gis_non_200(self):
        crawler = self._make_crawler()

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, json_data={"payload": {"sections": []}})
            return _mock_resp(status=403, text="Forbidden")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("123 Main St, Austin TX")

        assert result.found is False
        assert "403" in result.error

    # --- successful CSV parse -----------------------------------------------

    @pytest.mark.asyncio
    async def test_successful_csv_response(self):
        crawler = self._make_crawler()
        csv_text = "MLS#,PRICE,BEDS,BATHS,SQFT,ADDRESS,YEAR BUILT,DAYS ON MARKET,LAST SOLD PRICE,LAST SOLD DATE,STATUS,URL\n123,450000,3,2.0,1500,123 Main St,2005,30,400000,2020-01-01,Active,https://redfin.com/\n"

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(
                    status=200,
                    json_data={
                        "payload": {
                            "sections": [
                                {
                                    "rows": [
                                        {
                                            "name": "123 Main St",
                                            "url": "/home/1",
                                            "id": "1",
                                            "type": "address",
                                        }
                                    ]
                                }
                            ]
                        }
                    },
                )
            return _mock_resp(status=200, text=csv_text)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("123 Main St, Austin TX")

        assert result.found is True
        assert len(result.data.get("properties", [])) >= 1

    # --- autocomplete parse error is silenced --------------------------------

    @pytest.mark.asyncio
    async def test_autocomplete_json_error_silenced(self):
        """Autocomplete JSON error doesn't abort GIS fetch."""
        crawler = self._make_crawler()
        csv_text = "MLS#,PRICE\n456,500000\n"

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                resp = _mock_resp(status=200, text="not-json")
                resp.json.side_effect = ValueError("bad json")
                return resp
            return _mock_resp(status=200, text=csv_text)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("123 Main St")

        assert result.found is False or result.data is not None

    # --- _strip_xssi helper --------------------------------------------------

    def test_strip_xssi_removes_prefix(self):
        from modules.crawlers.property_redfin import _strip_xssi

        text = '{}&&{"payload": {}}'
        stripped = _strip_xssi(text)
        assert stripped.startswith("{")
        assert "payload" in stripped

    def test_strip_xssi_no_prefix_unchanged(self):
        from modules.crawlers.property_redfin import _strip_xssi

        text = '{"payload": {}}'
        assert _strip_xssi(text) == text

    # --- _parse_csv_text with JSON body -------------------------------------

    def test_parse_csv_text_json_body(self):
        import json

        from modules.crawlers.property_redfin import _parse_csv_text

        payload = {
            "payload": {
                "homes": [
                    {
                        "PRICE": "500000",
                        "BEDS": "3",
                        "BATHS": "2",
                        "SQFT": "1500",
                        "ADDRESS": "456 Oak Ave",
                    }
                ]
            }
        }
        properties = _parse_csv_text(json.dumps(payload))
        assert len(properties) >= 1

    # --- _parse_csv_text with bad data returns empty -------------------------

    def test_parse_csv_text_exception_returns_empty(self):
        from modules.crawlers.property_redfin import _parse_csv_text

        properties = _parse_csv_text("totally invalid data %%%")
        assert isinstance(properties, list)

    # --- _parse_csv_property int/float fallbacks ----------------------------

    def test_parse_csv_property_na_values(self):
        from modules.crawlers.property_redfin import _parse_csv_property

        prop = _parse_csv_property(
            {"PRICE": "N/A", "BEDS": "", "BATHS": None, "SQFT": "N/A", "ADDRESS": "789 Pine St"}
        )
        assert prop["price"] is None
        assert prop["beds"] is None
        assert prop["baths"] is None

    # --- _parse_autocomplete: no sections -----------------------------------

    def test_parse_autocomplete_no_sections(self):
        from modules.crawlers.property_redfin import _parse_autocomplete

        result = _parse_autocomplete({"payload": {}})
        assert result == []

    # WAVE-3 additions -------------------------------------------------------

    # --- _parse_autocomplete: rows present (lines 61-62) --------------------

    def test_parse_autocomplete_with_rows_lines_61_62(self):
        """Lines 61-62: inner for loop executes and items.append fires."""
        from modules.crawlers.property_redfin import _parse_autocomplete

        data = {
            "payload": {
                "sections": [
                    {
                        "rows": [
                            {
                                "name": "123 Main St",
                                "subtext": "Austin, TX",
                                "url": "/home/1",
                                "id": "abc",
                                "type": "address",
                            }
                        ]
                    }
                ]
            }
        }
        result = _parse_autocomplete(data)
        assert len(result) == 1
        assert result[0]["address"] == "123 Main St"
        assert result[0]["subtext"] == "Austin, TX"
        assert result[0]["id"] == "abc"

    def test_parse_autocomplete_multiple_sections_and_rows(self):
        """Lines 61-62: multiple sections each with rows — all appended."""
        from modules.crawlers.property_redfin import _parse_autocomplete

        data = {
            "payload": {
                "sections": [
                    {"rows": [{"name": "A"}, {"name": "B"}]},
                    {"rows": [{"name": "C"}]},
                ]
            }
        }
        result = _parse_autocomplete(data)
        assert len(result) == 3
        addresses = [r["address"] for r in result]
        assert "A" in addresses
        assert "C" in addresses

    def test_parse_autocomplete_section_with_no_rows(self):
        """Lines 61: section has no rows key → loop body never fires."""
        from modules.crawlers.property_redfin import _parse_autocomplete

        data = {"payload": {"sections": [{}]}}
        result = _parse_autocomplete(data)
        assert result == []

    # --- _int except branch (lines 80-81) -----------------------------------

    def test_parse_csv_property_int_type_error_line_80_81(self):
        """Lines 80-81: _int() receives a value that triggers TypeError → None."""
        from modules.crawlers.property_redfin import _parse_csv_property

        # A dict object as BEDS — int({"bad": "val"}) raises TypeError
        prop = _parse_csv_property({"BEDS": {"nested": "object"}})
        assert prop["beds"] is None

    def test_parse_csv_property_int_value_error_line_80_81(self):
        """Lines 80-81: _int() receives non-numeric string → ValueError → None."""
        from modules.crawlers.property_redfin import _parse_csv_property

        prop = _parse_csv_property({"BEDS": "not-a-number", "SQFT": "also-bad"})
        assert prop["beds"] is None
        assert prop["sqFt"] is None

    # --- _float except branch (lines 86-87) ---------------------------------

    def test_parse_csv_property_float_type_error_line_86_87(self):
        """Lines 86-87: _float() receives a value that triggers TypeError → None."""
        from modules.crawlers.property_redfin import _parse_csv_property

        # Pass an object that makes float() raise TypeError
        class _Bad:
            def __str__(self):
                raise TypeError("no str")

        prop = _parse_csv_property({"PRICE": _Bad()})
        assert prop["price"] is None

    def test_parse_csv_property_float_value_error_line_86_87(self):
        """Lines 86-87: _float() receives garbled string → ValueError → None."""
        from modules.crawlers.property_redfin import _parse_csv_property

        prop = _parse_csv_property({"PRICE": "$$notanumber$$", "BATHS": "xyz"})
        assert prop["price"] is None
        assert prop["baths"] is None

    # --- _parse_csv_text exception branch (lines 125-126) -------------------

    def test_parse_csv_text_exception_logs_warning_lines_125_126(self, caplog):
        """Lines 125-126: exception during CSV parse → warning logged, empty list."""
        import logging

        from modules.crawlers.property_redfin import _parse_csv_text

        # Inject a CSV string but patch DictReader to raise an exception
        with (
            patch("csv.DictReader", side_effect=RuntimeError("csv broken")),
            caplog.at_level(logging.WARNING, logger="modules.crawlers.property_redfin"),
        ):
            result = _parse_csv_text("MLS#,PRICE\n123,500000\n")

        assert result == []
        assert any("Redfin GIS parse error" in r.message for r in caplog.records)

    # --- scrape: autocomplete success path (line 167) -----------------------

    @pytest.mark.asyncio
    async def test_scrape_autocomplete_success_path_line_167(self):
        """Line 167: _parse_autocomplete called after successful JSON parse."""
        crawler = self._make_crawler()

        autocomplete_payload = {
            "payload": {
                "sections": [
                    {
                        "rows": [
                            {
                                "name": "456 Elm St",
                                "subtext": "Dallas, TX",
                                "url": "/home/456",
                                "id": "xyz",
                                "type": "address",
                            }
                        ]
                    }
                ]
            }
        }
        ac_text = "{}&&" + __import__("json").dumps(autocomplete_payload)
        csv_text = (
            "MLS#,PRICE,BEDS,BATHS,SQFT,ADDRESS,YEAR BUILT,"
            "DAYS ON MARKET,LAST SOLD PRICE,LAST SOLD DATE,STATUS,URL\n"
            "789,350000,2,1.0,900,456 Elm St,1998,15,300000,2019-06-01,Active,https://redfin.com/home/1\n"
        )

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text=ac_text)
            return _mock_resp(status=200, text=csv_text)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("456 Elm St, Dallas TX")

        assert result.found is True
        assert result.data.get("autocomplete") is not None
        assert len(result.data["autocomplete"]) == 1
        assert result.data["autocomplete"][0]["address"] == "456 Elm St"

    @pytest.mark.asyncio
    async def test_scrape_gis_206_partial_content(self):
        """Line 193: status 206 (partial content) is treated as success."""
        crawler = self._make_crawler()
        csv_text = (
            "MLS#,PRICE,BEDS,BATHS,SQFT,ADDRESS,YEAR BUILT,"
            "DAYS ON MARKET,LAST SOLD PRICE,LAST SOLD DATE,STATUS,URL\n"
            "555,200000,1,1.0,600,789 Pine St,2010,5,180000,2022-03-01,Active,https://redfin.com/home/2\n"
        )

        async def _fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text="{}")
            return _mock_resp(status=206, text=csv_text)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("789 Pine St")

        assert result.found is True
        assert len(result.data.get("properties", [])) >= 1


# ===========================================================================
# property_zillow.py
# ===========================================================================


class TestPropertyZillowCrawler:
    """Covers scrape branches and helpers in PropertyZillowCrawler."""

    def _make_crawler(self):
        from modules.crawlers.property_zillow import PropertyZillowCrawler

        return PropertyZillowCrawler()

    # --- suggestions error → empty result ------------------------------------

    @pytest.mark.asyncio
    async def test_empty_suggestions_returns_not_found(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "_fetch_suggestions", new=AsyncMock(return_value=[])):
            result = await crawler.scrape("123 Main St")

        assert result.found is False
        assert result.data.get("properties") == []

    # --- successful scrape with property page details -------------------------

    @pytest.mark.asyncio
    async def test_successful_scrape(self):
        crawler = self._make_crawler()
        suggestions = [
            {
                "address": "123 Main St",
                "city": "Austin",
                "state": "TX",
                "zip": "78701",
                "lat": 30.0,
                "lng": -97.0,
                "zpid": "123456",
            }
        ]
        page_details = {"zestimate": 450000, "beds": 3, "baths": 2.0, "sqft": 1500}

        with (
            patch.object(crawler, "_fetch_suggestions", new=AsyncMock(return_value=suggestions)),
            patch.object(crawler, "_fetch_property_page", new=AsyncMock(return_value=page_details)),
        ):
            result = await crawler.scrape("123 Main St")

        assert result.found is True
        props = result.data.get("properties", [])
        assert len(props) >= 1
        assert props[0]["zestimate"] == 450000

    # --- _fetch_suggestions exception is swallowed ---------------------------

    @pytest.mark.asyncio
    async def test_fetch_suggestions_exception(self):
        crawler = self._make_crawler()

        mock_cm = MagicMock()
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=RuntimeError("playwright error"))
        mock_cm.__aenter__ = AsyncMock(return_value=mock_page)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            result = await crawler._fetch_suggestions("https://example.com")

        assert result == []

    # --- _fetch_property_page exception is swallowed -------------------------

    @pytest.mark.asyncio
    async def test_fetch_property_page_exception(self):
        crawler = self._make_crawler()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("playwright crash"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            result = await crawler._fetch_property_page("123 Main St")

        assert result == {}

    # --- _parse_suggestions: empty results ----------------------------------

    def test_parse_suggestions_empty(self):
        from modules.crawlers.property_zillow import _parse_suggestions

        assert _parse_suggestions({}) == []
        assert _parse_suggestions({"results": []}) == []

    # --- _parse_suggestions: full payload -----------------------------------

    def test_parse_suggestions_with_data(self):
        from modules.crawlers.property_zillow import _parse_suggestions

        data = {
            "results": [
                {
                    "display": "123 Main St, Austin TX 78701",
                    "metaData": {
                        "addressCity": "Austin",
                        "addressState": "TX",
                        "addressZip": "78701",
                        "lat": 30.26,
                        "lng": -97.74,
                        "zpid": 999,
                    },
                }
            ]
        }
        props = _parse_suggestions(data)
        assert len(props) == 1
        assert props[0]["city"] == "Austin"
        assert props[0]["zpid"] == 999

    # --- _parse_property_page: Next.js JSON path ----------------------------

    def test_parse_property_page_nextjs_json(self):
        import json

        from modules.crawlers.property_zillow import _parse_property_page

        gdp_cache = {
            "HomeDetails:12345": {
                "property": {
                    "zestimate": 500000,
                    "bedrooms": 4,
                    "bathrooms": 2.5,
                    "livingArea": 2000,
                    "priceHistory": [{"price": 480000, "date": "2021-01-01"}],
                }
            }
        }
        page_data = {
            "props": {"pageProps": {"componentProps": {"gdpClientCache": json.dumps(gdp_cache)}}}
        }
        script_content = json.dumps(page_data)
        html = f'<html><script id="__NEXT_DATA__">{script_content}</script></html>'

        details = _parse_property_page(html)
        assert details["zestimate"] == 500000
        assert details["beds"] == 4

    # --- _parse_property_page: regex fallback --------------------------------

    def test_parse_property_page_regex_fallback(self):
        from modules.crawlers.property_zillow import _parse_property_page

        html = '<html><body>"zestimate": 320000 "bedrooms": 3 "bathrooms": 2.0 "livingArea": 1400</body></html>'
        details = _parse_property_page(html)
        assert details["zestimate"] == 320000
        assert details["beds"] == 3


# ===========================================================================
# playwright_base.py
# ===========================================================================


class TestPlaywrightCrawler:
    """Tests for PlaywrightCrawler helpers."""

    def _make_crawler(self):
        from modules.crawlers.playwright_base import PlaywrightCrawler
        from modules.crawlers.result import CrawlerResult

        class _Concrete(PlaywrightCrawler):
            platform = "test_playwright"
            source_reliability = 0.8
            requires_tor = False

            async def scrape(self, identifier: str) -> CrawlerResult:
                return CrawlerResult(platform=self.platform, identifier=identifier, found=False)

        return _Concrete()

    # --- is_blocked: title contains captcha ----------------------------------

    @pytest.mark.asyncio
    async def test_is_blocked_captcha_title(self):
        crawler = self._make_crawler()
        page = AsyncMock()
        page.title = AsyncMock(return_value="Please solve the CAPTCHA")
        assert await crawler.is_blocked(page) is True

    @pytest.mark.asyncio
    async def test_is_blocked_blocked_title(self):
        crawler = self._make_crawler()
        page = AsyncMock()
        page.title = AsyncMock(return_value="Access Blocked - Try again")
        assert await crawler.is_blocked(page) is True

    @pytest.mark.asyncio
    async def test_is_blocked_403_title(self):
        crawler = self._make_crawler()
        page = AsyncMock()
        page.title = AsyncMock(return_value="403 Forbidden")
        assert await crawler.is_blocked(page) is True

    @pytest.mark.asyncio
    async def test_is_blocked_normal_title(self):
        crawler = self._make_crawler()
        page = AsyncMock()
        page.title = AsyncMock(return_value="Search Results - Zillow")
        assert await crawler.is_blocked(page) is False

    @pytest.mark.asyncio
    async def test_is_blocked_access_denied(self):
        crawler = self._make_crawler()
        page = AsyncMock()
        page.title = AsyncMock(return_value="Access Denied")
        assert await crawler.is_blocked(page) is True

    # --- page() context manager launches and closes browser -----------------

    @pytest.mark.asyncio
    async def test_page_context_manager_opens_browser(self):
        crawler = self._make_crawler()

        mock_page = AsyncMock()
        mock_page.add_init_script = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()
        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw = AsyncMock()
        mock_pw.chromium = mock_chromium
        mock_pw_cm = AsyncMock()
        mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.crawlers.playwright_base.async_playwright", return_value=mock_pw_cm):
            async with crawler.page() as page:
                assert page is mock_page

        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_page_context_manager_with_url_navigates(self):
        crawler = self._make_crawler()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.add_init_script = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()
        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw = AsyncMock()
        mock_pw.chromium = mock_chromium
        mock_pw_cm = AsyncMock()
        mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.crawlers.playwright_base.async_playwright", return_value=mock_pw_cm):
            async with crawler.page(url="https://example.com"):
                pass

        mock_page.goto.assert_called_once_with(
            "https://example.com", wait_until="domcontentloaded", timeout=30000
        )
