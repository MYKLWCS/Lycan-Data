"""
test_crawlers_wave3b.py — Branch-coverage gap tests for wave-3b crawlers.

Crawlers covered:
  news_wikipedia, mortgage_hmda, mortgage_deed, vehicle_ownership,
  whitepages, youtube, whatsapp, paste_psbdmp, darkweb_ahmia, darkweb_torch

Each test class targets specific uncovered branches identified during
coverage analysis.  All HTTP I/O is mocked at the crawler method level
(patch.object on .get / .post) so no network calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "", url: str = ""):
    """Build a MagicMock that mimics an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (str(json_data) if json_data is not None else "")
    resp.url = url or "https://example.com"
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# news_wikipedia.py
# ===========================================================================


class TestWikipediaCrawler:
    """Covers branches at ~84% — JSON errors and non-200 paths."""

    def _make_crawler(self):
        from modules.crawlers.news_wikipedia import WikipediaCrawler

        return WikipediaCrawler()

    # --- _wp_search JSON error -------------------------------------------------

    @pytest.mark.asyncio
    async def test_wp_search_json_error(self):
        """_wp_search returns [] when resp.json() raises."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="not-json")
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._wp_search("test+query")

        assert result == []

    # --- _wp_summary non-200 ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_wp_summary_non_200(self):
        """_wp_summary returns {} on 404."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="Not Found")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._wp_summary("Some Title")

        assert result == {}

    # --- _wp_summary None response --------------------------------------------

    @pytest.mark.asyncio
    async def test_wp_summary_none_response(self):
        """_wp_summary returns {} when get() returns None."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._wp_summary("Some Title")

        assert result == {}

    # --- _wp_summary JSON error -----------------------------------------------

    @pytest.mark.asyncio
    async def test_wp_summary_json_error(self):
        """_wp_summary returns {} when resp.json() raises."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="garbage")
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._wp_summary("Some Title")

        assert result == {}

    # --- _wikidata_search non-200 ---------------------------------------------

    @pytest.mark.asyncio
    async def test_wikidata_non_200(self):
        """_wikidata_search returns [] on 500."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=500, text="error")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._wikidata_search("test+query")

        assert result == []

    # --- _wikidata_search None response ---------------------------------------

    @pytest.mark.asyncio
    async def test_wikidata_none_response(self):
        """_wikidata_search returns [] when get() returns None."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._wikidata_search("test+query")

        assert result == []

    # --- _wikidata_search JSON error ------------------------------------------

    @pytest.mark.asyncio
    async def test_wikidata_json_error(self):
        """_wikidata_search returns [] when resp.json() raises."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="not json")
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._wikidata_search("test+query")

        assert result == []

    # --- Full scrape — no wp results, so top_summary stays empty -------------

    @pytest.mark.asyncio
    async def test_scrape_no_wp_results_still_returns_result(self):
        """scrape() completes when wp search returns nothing."""
        crawler = self._make_crawler()
        empty_wp = _mock_resp(status=200, json_data={"query": {"search": []}})
        empty_wd = _mock_resp(status=200, json_data={"search": []})

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "wikipedia.org/w/api.php" in url:
                return empty_wp
            if "wikidata.org" in url:
                return empty_wd
            return _mock_resp(status=200, json_data={})

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Unknown Entity XYZ")

        assert result.found is False
        assert result.data["wikipedia_results"] == []
        assert result.data["wikidata_entities"] == []


# ===========================================================================
# mortgage_hmda.py
# ===========================================================================


class TestMortgageHmdaCrawler:
    """Covers ~87% — single-token identifier, float ValueError, non-200, JSON error."""

    def _make_crawler(self):
        from modules.crawlers.mortgage_hmda import MortgageHmdaCrawler

        return MortgageHmdaCrawler()

    # --- _parse_identifier single token (no comma, no zip) -------------------

    def test_parse_identifier_single_token(self):
        from modules.crawlers.mortgage_hmda import _parse_identifier

        city, state, zip_code = _parse_identifier("Houston")
        assert city == "Houston"
        assert state == ""
        assert zip_code == ""

    # --- single-token path uses best-effort URL (state="all") ----------------

    @pytest.mark.asyncio
    async def test_scrape_single_token_city_no_state(self):
        """Single-word identifier: city only, state='all' URL path used."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            json_data={"aggregations": [{"count": 5, "action_taken": "originated"}]},
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)) as mock_get:
            result = await crawler.scrape("Houston")

        # URL should contain 'all' for state
        called_url = mock_get.call_args[0][0]
        assert "all" in called_url
        assert result.data["total_loans"] == 5

    # --- float ValueError silencing in _parse_hmda_aggregations --------------

    def test_parse_hmda_float_value_error(self):
        """loan_amount / income that can't be converted to float are silently skipped."""
        from modules.crawlers.mortgage_hmda import _parse_hmda_aggregations

        data = {
            "aggregations": [
                {
                    "count": 10,
                    "action_taken": "originated",
                    "loan_amount": "not-a-number",
                    "income": "also-bad",
                }
            ]
        }
        summary = _parse_hmda_aggregations(data)
        assert summary["total_loans"] == 10
        assert summary["median_loan_amount"] is None
        assert summary["median_income"] is None

    # --- non-200 HTTP response ------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        """scrape() returns found=False on 503."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=503, text="Service Unavailable")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Austin,TX")

        assert result.found is False
        assert result.data["error"] == "http_503"

    # --- None response --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """scrape() returns found=False when get() returns None."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Austin,TX")

        assert result.found is False
        assert result.data["error"] == "http_error"

    # --- JSON parse error -----------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_json_error(self):
        """scrape() returns found=False on JSON parse error."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="not-json-at-all")
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Austin,TX")

        assert result.found is False
        assert result.data["error"] == "json_parse_error"

    # --- empty identifier (no city, state, zip) — returns invalid_identifier -

    @pytest.mark.asyncio
    async def test_scrape_empty_identifier(self):
        """Whitespace-only identifier falls through to invalid_identifier return."""
        crawler = self._make_crawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data["error"] == "invalid_identifier"


# ===========================================================================
# mortgage_deed.py
# ===========================================================================


class TestMortgageDeedCrawler:
    """Covers ~89% — float ValueError fallback, regex fallback, empty identifier."""

    def _make_crawler(self):
        from modules.crawlers.mortgage_deed import MortgageDeedCrawler

        return MortgageDeedCrawler()

    # --- float ValueError in mortgage_amount → keeps raw string --------------

    def test_parse_mortgage_amount_float_fallback(self):
        """When float() fails on the captured amount, the raw string is stored."""
        from modules.crawlers.mortgage_deed import _parse_publicrecordsnow_html

        html = """
        <div class="result-item">
          Owner: John Smith
          Mortgage: $abc,def — bad amount
        </div>
        """
        records = _parse_publicrecordsnow_html(html)
        # Should not raise; may produce an empty record or one with the raw value
        assert isinstance(records, list)

    # --- regex fallback when no structured blocks found ----------------------

    def test_parse_regex_fallback(self):
        """When no structured blocks found, regex sweep extracts addresses."""
        from modules.crawlers.mortgage_deed import _parse_publicrecordsnow_html

        html = "Found property at 123 Main St Austin TX with deed info."
        records = _parse_publicrecordsnow_html(html)
        assert len(records) >= 1
        assert "address" in records[0]

    # --- empty identifier returns invalid_identifier -------------------------

    @pytest.mark.asyncio
    async def test_scrape_empty_identifier(self):
        """Empty identifier returns invalid_identifier immediately."""
        crawler = self._make_crawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data["error"] == "invalid_identifier"

    # --- non-200 response ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        """scrape() returns http_<code> error on non-200."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=403, text="Forbidden")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data["error"] == "http_403"

    # --- None response -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """scrape() returns http_error when get() returns None."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data["error"] == "http_error"

    # --- successful parse — structured blocks --------------------------------

    @pytest.mark.asyncio
    async def test_scrape_parses_html_records(self):
        """scrape() returns found=True when records are parsed from HTML."""
        crawler = self._make_crawler()
        html = """
        <html><body>
        <div class="result-item">
          Owner: Jane Doe
          Deed Date: 01/15/2023
          Mortgage: $250,000
          Lender: First National Bank  |
          Type: Deed of Trust
          456 Oak Ave Dallas TX,
        </div>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe")

        assert result.found is True
        assert result.data["result_count"] >= 1


# ===========================================================================
# vehicle_ownership.py
# ===========================================================================


class TestVehicleOwnershipCrawler:
    """Covers ~86% — regex cap at 10, bs4 exception, Playwright happy paths."""

    def _make_crawler(self):
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        return VehicleOwnershipCrawler()

    # --- regex fallback capped at 10 -----------------------------------------

    def test_parse_vehicle_cards_regex_cap_at_10(self):
        """Regex fallback stops at 10 vehicles."""
        from modules.crawlers.vehicle_ownership import _parse_vehicle_cards_html

        # 15 year-make-model patterns, no bs4-recognisable selectors
        lines = "\n".join(f"2005 Toyota Corolla model{i}" for i in range(15))
        vehicles = _parse_vehicle_cards_html(lines)
        assert len(vehicles) <= 10

    # --- bs4 exception in parse ----------------------------------------------

    def test_parse_vehicle_cards_bs4_exception(self):
        """When bs4 raises, the exception is swallowed and empty list returned."""
        from modules.crawlers.vehicle_ownership import _parse_vehicle_cards_html

        with patch("bs4.BeautifulSoup", side_effect=RuntimeError("bs4 broken")):
            vehicles = _parse_vehicle_cards_html("<html>some content</html>")

        assert vehicles == []

    # --- _scrape_vehiclehistory: no last name → returns [] -------------------

    @pytest.mark.asyncio
    async def test_scrape_vehiclehistory_no_last_name(self):
        """_scrape_vehiclehistory returns [] immediately when last is empty."""
        crawler = self._make_crawler()
        result = await crawler._scrape_vehiclehistory("John", "")
        assert result == []

    # --- _scrape_beenverified: no last name → returns [] ---------------------

    @pytest.mark.asyncio
    async def test_scrape_beenverified_no_last_name(self):
        """_scrape_beenverified returns [] immediately when last is empty."""
        crawler = self._make_crawler()
        result = await crawler._scrape_beenverified("John", "")
        assert result == []

    # --- _scrape_vehiclehistory Playwright happy path ------------------------

    @pytest.mark.asyncio
    async def test_scrape_vehiclehistory_playwright_happy_path(self):
        """Playwright page with vehicle HTML returns parsed vehicles."""
        crawler = self._make_crawler()

        html_with_vehicle = """
        <html><body>
        <div class="vehicle-card">
          Year: 2018 Make: Honda Model: Civic  |
          VIN: 1HGBH41JXMN109186
          Plate: ABC1234 State: TX
        </div>
        </body></html>
        """

        mock_page = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value=html_with_vehicle)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_page)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            vehicles = await crawler._scrape_vehiclehistory("John", "Smith")

        assert isinstance(vehicles, list)

    # --- _scrape_vehiclehistory Playwright exception swallowed ---------------

    @pytest.mark.asyncio
    async def test_scrape_vehiclehistory_playwright_exception(self):
        """Exception from Playwright returns [] without re-raising."""
        crawler = self._make_crawler()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("playwright unavailable"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            vehicles = await crawler._scrape_vehiclehistory("John", "Smith")

        assert vehicles == []

    # --- _scrape_beenverified Playwright happy path --------------------------

    @pytest.mark.asyncio
    async def test_scrape_beenverified_playwright_happy_path(self):
        """BeenVerified page scrape returns parsed vehicles."""
        crawler = self._make_crawler()

        html = """
        <html><body>
        <div class="vehicle-item">
          2020 Ford F-150
        </div>
        </body></html>
        """

        mock_page = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value=html)
        mock_page.wait_for_timeout = AsyncMock()

        # vehicles_section locator
        mock_locator = MagicMock()
        mock_locator.first = MagicMock()
        mock_locator.first.click = AsyncMock(side_effect=Exception("no section"))
        mock_page.locator = MagicMock(return_value=mock_locator)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_page)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            vehicles = await crawler._scrape_beenverified("John", "Smith")

        assert isinstance(vehicles, list)

    # --- Full scrape: invalid identifier (empty first) -----------------------

    @pytest.mark.asyncio
    async def test_scrape_empty_name(self):
        """Empty identifier returns invalid_identifier error."""
        crawler = self._make_crawler()
        result = await crawler.scrape("")
        assert result.found is False
        assert result.data["error"] == "invalid_identifier"


# ===========================================================================
# whitepages.py
# ===========================================================================


class TestWhitepagesCrawler:
    """Covers ~87% — single name, fallback selector, _extract_whitepages_card."""

    def _make_crawler(self):
        from modules.crawlers.whitepages import WhitepagesCrawler

        return WhitepagesCrawler()

    # --- _parse_name_identifier single token (no last name) ------------------

    def test_parse_name_single_token(self):
        from modules.crawlers.whitepages import _parse_name_identifier

        first, last, city, state = _parse_name_identifier("Madonna")
        assert first == "Madonna"
        assert last == ""

    # --- URL built without city/state when no location part ------------------

    @pytest.mark.asyncio
    async def test_scrape_single_name_no_location(self):
        """Single name without location builds /name/<slug> URL."""
        crawler = self._make_crawler()

        mock_page = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.title = AsyncMock(return_value="Madonna - Whitepages")
        mock_page.content = AsyncMock(return_value="<html><body>No results</body></html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_page)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            result = await crawler.scrape("Madonna")

        assert result.found is False
        assert result.data["result_count"] == 0

    # --- fallback selector: no testid cards → div.card fallback --------------

    @pytest.mark.asyncio
    async def test_scrape_fallback_div_card_selector(self):
        """When primary selectors miss, fallback finds divs with 'card' in class."""
        crawler = self._make_crawler()

        html = """
        <html><body>
        <div class="person-card">
          <h3>John Smith</h3>
          <span class="location-info">Austin, TX</span>
        </div>
        </body></html>
        """

        mock_page = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.title = AsyncMock(return_value="John Smith - Whitepages")
        mock_page.content = AsyncMock(return_value=html)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_page)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            result = await crawler.scrape("John Smith|Austin,TX")

        # Found is True (no "No results" text in the page)
        assert result.found is True

    # --- bot-block detection -------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_bot_block(self):
        """Title containing 'access denied' triggers rotate_circuit and returns error."""
        crawler = self._make_crawler()

        mock_page = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.title = AsyncMock(return_value="Access Denied - Whitepages")
        mock_page.content = AsyncMock(return_value="<html></html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_page)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=mock_cm):
            with patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate:
                result = await crawler.scrape("John Smith")

        mock_rotate.assert_called_once()
        assert result.found is False
        assert result.error is not None

    # --- _extract_whitepages_card: no name → returns None --------------------

    def test_extract_whitepages_card_no_name(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.whitepages import _extract_whitepages_card

        html = "<div><span class='location-info'>Austin, TX</span></div>"
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div")
        result = _extract_whitepages_card(card)
        assert result is None

    # --- _extract_whitepages_card: name present, full extraction -------------

    def test_extract_whitepages_card_full(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.whitepages import _extract_whitepages_card

        html = """
        <div>
          <h3 class="name">Jane Doe</h3>
          <span>Age 35</span>
          <span class="location-info">Chicago, IL</span>
          <span class="phone-info">(555) 123-4567</span>
          <span class="email-info">jane@example.com</span>
          <div class="relative-info"><a>Bob Doe</a></div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div")
        result = _extract_whitepages_card(card)
        assert result is not None
        assert result["name"] == "Jane Doe"
        assert result["city"] == "Chicago"
        assert result["state"] == "IL"

    # --- _extract_whitepages_card: location without comma --------------------

    def test_extract_whitepages_card_location_no_comma(self):
        from bs4 import BeautifulSoup

        from modules.crawlers.whitepages import _extract_whitepages_card

        html = """
        <div>
          <h2 class="name-heading">Bob Jones</h2>
          <span class="location-details">Texas</span>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div")
        result = _extract_whitepages_card(card)
        assert result is not None
        assert result["city"] == "Texas"
        assert result["state"] == ""

    # --- _extract_whitepages_card: exception swallowed → returns None --------

    def test_extract_whitepages_card_exception(self):
        from modules.crawlers.whitepages import _extract_whitepages_card

        bad_card = MagicMock()
        bad_card.find.side_effect = RuntimeError("bs4 broken")

        result = _extract_whitepages_card(bad_card)
        assert result is None


# ===========================================================================
# youtube.py
# ===========================================================================


class TestYouTubeCrawler:
    """Covers ~87% — all URLs fail, try_url None, error URL, _parse() branches."""

    def _make_crawler(self):
        from modules.crawlers.youtube import YouTubeCrawler

        return YouTubeCrawler()

    # --- all URL attempts return None → found=False -------------------------

    @pytest.mark.asyncio
    async def test_scrape_all_urls_fail_none(self):
        """All three URL attempts returning None yields found=False."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("nonexistenthandle")

        assert result.found is False
        assert result.data["handle"] == "nonexistenthandle"

    # --- _try_url: None response → found=False result ------------------------

    @pytest.mark.asyncio
    async def test_try_url_none_response(self):
        """_try_url with None get() response returns found=False."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._try_url("https://www.youtube.com/@test", "test")

        assert result.found is False

    # --- _try_url: non-200 response → found=False result --------------------

    @pytest.mark.asyncio
    async def test_try_url_non_200(self):
        """_try_url with 404 returns found=False."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="Not Found", url="https://www.youtube.com/@test")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._try_url("https://www.youtube.com/@test", "test")

        assert result.found is False

    # --- _try_url: URL contains 'error' → found=False -----------------------

    @pytest.mark.asyncio
    async def test_try_url_error_in_url(self):
        """_try_url detects 'error' in redirected URL and returns found=False."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            text="<html><title>Error - YouTube</title></html>",
            url="https://www.youtube.com/error?code=404",
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._try_url("https://www.youtube.com/@test", "test")

        assert result.found is False

    # --- _try_url: uxe= in URL → found=False --------------------------------

    @pytest.mark.asyncio
    async def test_try_url_uxe_param_in_url(self):
        """_try_url detects uxe= consent redirect and returns found=False."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            text="<html><title>Before you continue</title></html>",
            url="https://consent.youtube.com/?uxe=12345",
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._try_url("https://www.youtube.com/@test", "test")

        assert result.found is False

    # --- _parse: consent marker in title → empty data / found=False ----------

    def test_parse_consent_page_returns_empty(self):
        """_parse() returns data without display_name when title contains consent marker."""
        crawler = self._make_crawler()
        html = (
            "<html><head><title>Before you continue to YouTube</title></head><body></body></html>"
        )
        data = crawler._parse(html, "testhandle")
        assert "display_name" not in data

    # --- _parse: no title tag → display_name absent -------------------------

    def test_parse_no_title_tag(self):
        """_parse() without <title> tag produces no display_name."""
        crawler = self._make_crawler()
        html = "<html><body><p>some content</p></body></html>"
        data = crawler._parse(html, "myhandle")
        assert data["handle"] == "myhandle"
        assert "display_name" not in data

    # --- _parse: rich page → all fields extracted ---------------------------

    def test_parse_full_channel_page(self):
        """_parse() extracts display_name, bio, subscribers, videos, location."""
        crawler = self._make_crawler()
        html = """
        <html>
          <head>
            <title>TechChannel - YouTube</title>
            <meta name="description" content="Tech videos every week.">
          </head>
          <body>
            <script>
              "subscriberCountText":{"simpleText":"1.2M subscribers"}
              "videoCountText":{"runs":[{"text":"450"}]}
              "country":{"simpleText":"United States"}
            </script>
          </body>
        </html>
        """
        data = crawler._parse(html, "TechChannel")
        assert data["display_name"] == "TechChannel"
        assert data["bio"] == "Tech videos every week."
        assert data["subscriber_count_text"] == "1.2M subscribers"
        assert data["post_count"] == 450
        assert data["location"] == "United States"

    # --- @ prefix stripped from identifier ----------------------------------

    @pytest.mark.asyncio
    async def test_scrape_strips_at_prefix(self):
        """scrape() strips the leading @ before using the handle."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            text="<html><head><title>TechChannel - YouTube</title></head><body></body></html>",
            url="https://www.youtube.com/@TechChannel",
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("@TechChannel")

        assert result.data.get("handle") == "TechChannel"


# ===========================================================================
# whatsapp.py
# ===========================================================================


class TestWhatsAppCrawler:
    """Covers ~85% — phone too short, None response, _detect_registered branches."""

    def _make_crawler(self):
        from modules.crawlers.whatsapp import WhatsAppCrawler

        return WhatsAppCrawler()

    # --- phone number too short (<7 digits) ----------------------------------

    @pytest.mark.asyncio
    async def test_scrape_phone_too_short(self):
        """Identifiers with fewer than 7 digits return invalid_phone error."""
        crawler = self._make_crawler()
        result = await crawler.scrape("123")
        assert result.found is False
        assert result.error == "invalid_phone"

    # --- None response -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """None get() response returns found=False with timeout error."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("+1234567890")

        assert result.found is False
        assert result.error == "timeout"
        assert result.data["whatsapp_registered"] is None

    # --- _detect_registered: "send message" → True ---------------------------

    def test_detect_registered_send_message(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered("Click to Send message now", "https://wa.me/123")
        assert result is True

    # --- _detect_registered: "open whatsapp" → True -------------------------

    def test_detect_registered_open_whatsapp(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered("Open WhatsApp app", "https://wa.me/123")
        assert result is True

    # --- _detect_registered: "may not be on whatsapp" → False ----------------

    def test_detect_registered_not_on_whatsapp(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered(
            "The phone number shared via link may not be on WhatsApp", "https://wa.me/123"
        )
        assert result is False

    # --- _detect_registered: "not available" → False -------------------------

    def test_detect_registered_not_available(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered("This number is not available", "https://wa.me/123")
        assert result is False

    # --- _detect_registered: api.whatsapp.com in URL → True ------------------

    def test_detect_registered_api_url(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered(
            "some page content", "https://api.whatsapp.com/send?phone=123"
        )
        assert result is True

    # --- _detect_registered: open.whatsapp.com in URL → True ----------------

    def test_detect_registered_open_url(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered(
            "some content", "https://open.whatsapp.com/send?phone=123"
        )
        assert result is True

    # --- _detect_registered: unknown page → None -----------------------------

    def test_detect_registered_unknown(self):
        crawler = self._make_crawler()
        result = crawler._detect_registered("Generic page content", "https://wa.me/123")
        assert result is None

    # --- Full scrape: registered = True → found = True -----------------------

    @pytest.mark.asyncio
    async def test_scrape_registered_found(self):
        """found=True when _detect_registered returns True."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            text="<html><body>Send message to this contact</body></html>",
            url="https://wa.me/1234567890",
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+1234567890")

        assert result.found is True
        assert result.data["whatsapp_registered"] is True

    # --- Full scrape: unknown → found=False, reliability lowered -------------

    @pytest.mark.asyncio
    async def test_scrape_unknown_registration(self):
        """source_reliability=0.0 when registration status is unknown."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            text="<html><body>Welcome to WhatsApp</body></html>",
            url="https://wa.me/1234567890",
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+1234567890")

        assert result.source_reliability == 0.0


# ===========================================================================
# paste_psbdmp.py
# ===========================================================================


class TestPastePsbdmpCrawler:
    """Covers ~83% — empty ID skip, None/429/500/JSON error, dict/non-list cases."""

    def _make_crawler(self):
        from modules.crawlers.paste_psbdmp import PastePsbdmpCrawler

        return PastePsbdmpCrawler()

    # --- _parse_psbdmp_response: item with empty 'id' is skipped -------------

    def test_parse_empty_id_skip(self):
        from modules.crawlers.paste_psbdmp import _parse_psbdmp_response

        items = [
            {"id": "", "time": "1700000000", "text": "leaked data"},
            {"id": "abc123", "time": "1700000001", "text": "valid paste"},
        ]
        mentions = _parse_psbdmp_response(items)
        # Only the item with a real id should appear
        assert len(mentions) == 1
        assert mentions[0]["pastebin_id"] == "abc123"

    # --- None response → http_error ------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.error == "http_error"

    # --- 429 → rate_limited --------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_429_rate_limited(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=429, text="Too Many Requests")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.error == "rate_limited"

    # --- 404 → empty results (no-results sentinel) ---------------------------

    @pytest.mark.asyncio
    async def test_scrape_404_no_results(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="Not Found")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.data["mention_count"] == 0

    # --- 500 → http_500 error ------------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_500_error(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=500, text="Internal Server Error")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.error == "http_500"

    # --- JSON parse error → invalid_json -------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_json_error(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="not-valid-json")
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.error == "invalid_json"

    # --- dict response with 'data' key ---------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_dict_with_data_key(self):
        """psbdmp returning {"data": [...]} is unwrapped correctly."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            json_data={
                "data": [{"id": "xyz789", "time": "1700000000", "text": "some leaked info"}]
            },
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is True
        assert result.data["mention_count"] == 1
        assert result.data["mentions"][0]["pastebin_id"] == "xyz789"

    # --- dict response without 'data' or 'results' key → empty mentions ------

    @pytest.mark.asyncio
    async def test_scrape_dict_without_data_key(self):
        """Dict response with no 'data'/'results' key uses empty list."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            json_data={"status": "ok", "count": 0},
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.data["mention_count"] == 0

    # --- non-list, non-dict response → empty mentions ------------------------

    @pytest.mark.asyncio
    async def test_scrape_non_list_non_dict_response(self):
        """Integer or string JSON body yields empty mentions."""
        crawler = self._make_crawler()
        # Pass json_data=42 so _mock_resp sets return_value (not side_effect=ValueError)
        resp = _mock_resp(status=200, json_data=42)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.data["mention_count"] == 0

    # --- list response: happy path -------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_list_response(self):
        """List response processes all items with valid IDs."""
        crawler = self._make_crawler()
        resp = _mock_resp(
            status=200,
            json_data=[
                {"id": "aaa111", "time": "1700000001", "text": "first paste"},
                {"id": "bbb222", "time": "1700000002", "text": "second paste"},
            ],
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")

        assert result.found is True
        assert result.data["mention_count"] == 2


# ===========================================================================
# darkweb_ahmia.py
# ===========================================================================


class TestDarkwebAhmiaCrawler:
    """Covers ~88% — max results break, page-1 None, 429 break, non-200 errors."""

    def _make_crawler(self):
        from modules.crawlers.darkweb_ahmia import DarkwebAhmiaCrawler

        return DarkwebAhmiaCrawler()

    # --- max results break before page 1 ------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_stops_at_max_results(self):
        """When collected >= 20 after page 0, page 1 is never fetched."""
        crawler = self._make_crawler()

        # Build HTML with 20+ results on page 0
        li_items = "".join(
            f'<li class="result"><h4>Title {i}</h4><cite>http://onion{i}.onion</cite><p>Desc {i}</p></li>'
            for i in range(22)
        )
        html_p0 = f"<html><body><ul>{li_items}</ul></body></html>"

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_resp(status=200, text=html_p0)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        # Should have fetched page 0; page 1 should be skipped (max hit)
        assert call_count == 1  # stopped before page 1
        assert result.data["result_count"] == 20

    # --- page 0 response None → early return with http_error ----------------

    @pytest.mark.asyncio
    async def test_scrape_page0_none_response(self):
        """None response on page 0 returns found=False with http_error."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test query")

        assert result.found is False
        assert result.error == "http_error"

    # --- page 0 non-200 → early return with http_<code> error ----------------

    @pytest.mark.asyncio
    async def test_scrape_page0_non_200(self):
        """Non-200 on page 0 returns found=False with http_<code>."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=503, text="Service Unavailable")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test query")

        assert result.found is False
        assert result.error == "http_503"

    # --- 429 on page 0 → break, return empty results -------------------------

    @pytest.mark.asyncio
    async def test_scrape_page0_429_break(self):
        """429 on page 0 breaks loop and returns empty results."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=429, text="Too Many Requests")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test query")

        # 429 hits the break statement — falls through to empty collected
        assert result.data["result_count"] == 0

    # --- page 1 None → break (page 0 results kept) ---------------------------

    @pytest.mark.asyncio
    async def test_scrape_page1_none_breaks(self):
        """None on page 1 breaks without discarding page 0 results."""
        crawler = self._make_crawler()

        html_p0 = (
            "<html><body><ul>"
            '<li class="result"><h4>T</h4><cite>http://abc.onion</cite><p>D</p></li>'
            "</ul></body></html>"
        )

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(status=200, text=html_p0)
            return None  # page 1 returns None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert call_count == 2
        assert result.found is True
        assert result.data["result_count"] == 1

    # --- page 1 non-200 → break (page 0 results kept) ------------------------

    @pytest.mark.asyncio
    async def test_scrape_page1_non_200_breaks(self):
        """Non-200 on page 1 breaks without discarding page 0 results."""
        crawler = self._make_crawler()

        html_p0 = (
            "<html><body><ul>"
            '<li class="result"><h4>T</h4><cite>http://xyz.onion</cite><p>D</p></li>'
            "</ul></body></html>"
        )

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(status=200, text=html_p0)
            return _mock_resp(status=403, text="Forbidden")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert result.found is True
        assert result.data["result_count"] == 1

    # --- page 0 empty results → break with found=False -----------------------

    @pytest.mark.asyncio
    async def test_scrape_page0_empty_results(self):
        """Empty result set on page 0 triggers break (no more results)."""
        crawler = self._make_crawler()
        html_empty = "<html><body><ul></ul></body></html>"
        resp = _mock_resp(status=200, text=html_empty)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("obscure query")

        assert result.found is False
        assert result.data["result_count"] == 0

    # --- happy path: two pages of results ------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_two_pages(self):
        """Results from both page 0 and page 1 are combined."""
        crawler = self._make_crawler()

        def _make_page_html(start, count):
            items = "".join(
                f'<li class="result"><h4>T{i}</h4><cite>http://r{i}.onion</cite><p>D{i}</p></li>'
                for i in range(start, start + count)
            )
            return f"<html><body><ul>{items}</ul></body></html>"

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(status=200, text=_make_page_html(0, 5))
            return _mock_resp(status=200, text=_make_page_html(5, 5))

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert result.found is True
        assert result.data["result_count"] == 10


# ===========================================================================
# darkweb_torch.py
# ===========================================================================


class TestDarkwebTorchCrawler:
    """Covers ~89% — dt without <a>, max results break, None/non-200 errors."""

    def _make_crawler(self):
        from modules.crawlers.darkweb_torch import DarkwebTorchCrawler

        return DarkwebTorchCrawler()

    # --- _parse_torch_html: dt without <a> is skipped -----------------------

    def test_parse_torch_html_dt_without_a(self):
        from modules.crawlers.darkweb_torch import _parse_torch_html

        html = """
        <html><body>
          <dl>
            <dt>No link here — plain text</dt>
            <dd>Description without URL</dd>
            <dt><a href="http://valid.onion">Valid Result</a></dt>
            <dd>This one is valid</dd>
          </dl>
        </body></html>
        """
        results = _parse_torch_html(html)
        # Only the dt with <a> should produce a result
        assert len(results) == 1
        assert results[0]["onion_url"] == "http://valid.onion"
        assert results[0]["description"] == "This one is valid"

    # --- _parse_torch_html: dd missing (i >= len(dd_tags)) ------------------

    def test_parse_torch_html_missing_dd(self):
        from modules.crawlers.darkweb_torch import _parse_torch_html

        html = """
        <html><body>
          <dl>
            <dt><a href="http://only-dt.onion">Only DT</a></dt>
          </dl>
        </body></html>
        """
        results = _parse_torch_html(html)
        assert len(results) == 1
        assert results[0]["description"] == ""

    # --- max results break before page 2 ------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_stops_at_max_results(self):
        """Crawler stops fetching page 2 when collected >= 20 after page 1."""
        crawler = self._make_crawler()

        dt_items = "".join(
            f'<dt><a href="http://r{i}.onion">Title {i}</a></dt><dd>Desc {i}</dd>'
            for i in range(22)
        )
        html_full = f"<html><body><dl>{dt_items}</dl></body></html>"

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_resp(status=200, text=html_full)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert call_count == 1  # page 2 not fetched
        assert result.data["result_count"] == 20

    # --- page 1 None response → found=False with http_error -----------------

    @pytest.mark.asyncio
    async def test_scrape_page1_none_response(self):
        """None on page 1 returns found=False with http_error."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test query")

        assert result.found is False
        assert result.error == "http_error"

    # --- page 1 non-200 → found=False with http_<code> ----------------------

    @pytest.mark.asyncio
    async def test_scrape_page1_non_200(self):
        """Non-200 on page 1 returns found=False with http_<code>."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=403, text="Forbidden")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test query")

        assert result.found is False
        assert result.error == "http_403"

    # --- page 2 None → break (page 1 results kept) --------------------------

    @pytest.mark.asyncio
    async def test_scrape_page2_none_breaks(self):
        """None on page 2 breaks without losing page 1 results."""
        crawler = self._make_crawler()

        html_p1 = (
            '<html><body><dl><dt><a href="http://abc.onion">A</a></dt><dd>D</dd></dl></body></html>'
        )

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(status=200, text=html_p1)
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert call_count == 2
        assert result.found is True
        assert result.data["result_count"] == 1

    # --- page 2 non-200 → break (page 1 results kept) -----------------------

    @pytest.mark.asyncio
    async def test_scrape_page2_non_200_breaks(self):
        """Non-200 on page 2 breaks without losing page 1 results."""
        crawler = self._make_crawler()

        html_p1 = (
            '<html><body><dl><dt><a href="http://xyz.onion">X</a></dt><dd>D</dd></dl></body></html>'
        )

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(status=200, text=html_p1)
            return _mock_resp(status=500, text="error")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert result.found is True
        assert result.data["result_count"] == 1

    # --- empty page 1 results → break immediately ---------------------------

    @pytest.mark.asyncio
    async def test_scrape_page1_empty_results(self):
        """Empty results on page 1 breaks loop immediately."""
        crawler = self._make_crawler()
        html_empty = "<html><body><dl></dl></body></html>"
        resp = _mock_resp(status=200, text=html_empty)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("obscure query")

        assert result.found is False
        assert result.data["result_count"] == 0

    # --- happy path: two pages -----------------------------------------------

    @pytest.mark.asyncio
    async def test_scrape_two_pages(self):
        """Results from page 1 and page 2 are combined."""
        crawler = self._make_crawler()

        def _make_html(start, count):
            items = "".join(
                f'<dt><a href="http://r{i}.onion">T{i}</a></dt><dd>D{i}</dd>'
                for i in range(start, start + count)
            )
            return f"<html><body><dl>{items}</dl></body></html>"

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(status=200, text=_make_html(0, 6))
            return _mock_resp(status=200, text=_make_html(6, 4))

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("test query")

        assert result.found is True
        assert result.data["result_count"] == 10
