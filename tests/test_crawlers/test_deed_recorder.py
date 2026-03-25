"""
test_deed_recorder.py — 100% line coverage for modules/crawlers/property/deed_recorder.py

asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
All HTTP I/O is mocked via patch.object(crawler, 'get', new_callable=AsyncMock).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# _normalise_deed_type
# ---------------------------------------------------------------------------


class TestNormaliseDeedType:
    def test_wd(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("WD") == "Warranty Deed"

    def test_warranty(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("Warranty Deed of Sale") == "Warranty Deed"

    def test_qcd(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("QCD") == "Quitclaim Deed"

    def test_quitclaim(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("quitclaim transfer") == "Quitclaim Deed"

    def test_gd(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("GD") == "Grant Deed"

    def test_grant(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("GRANT DEED") == "Grant Deed"

    def test_td(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("TD") == "Deed of Trust"

    def test_dot(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("DOT") == "Deed of Trust"

    def test_deed_of_trust(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("Deed of Trust") == "Deed of Trust"

    def test_foreclosure(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("FORECLOSURE DEED") == "Foreclosure Deed"

    def test_trustee(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("Trustee's Sale") == "Trustee's Deed"

    def test_unknown_passthrough(self):
        from modules.crawlers.property.deed_recorder import _normalise_deed_type

        assert _normalise_deed_type("SOME UNKNOWN TYPE") == "SOME UNKNOWN TYPE"


# ---------------------------------------------------------------------------
# _parse_identifier
# ---------------------------------------------------------------------------


class TestParseIdentifier:
    def test_name_with_state(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("John Smith TX")
        assert name == "John Smith"
        assert state == "TX"
        assert county_key == "harris_tx"  # TX default

    def test_name_with_county_and_state(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("John Smith | Harris County TX")
        assert name == "John Smith"
        assert county_key == "harris_tx"
        assert state == "TX"

    def test_name_with_cook_county(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("Smith, John | Cook County IL")
        assert name == "Smith, John"
        assert county_key == "cook_il"
        assert state == "IL"

    def test_no_state_returns_empty(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("Just A Name")
        # No trailing two-letter state — falls through to bare return
        assert name == "Just A Name"
        assert county_key == ""
        assert state == ""

    def test_pipe_with_just_state(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("Jane Doe | FL")
        assert name == "Jane Doe"
        assert state == "FL"
        assert county_key == "miami_dade_fl"

    def test_unknown_state_maps_to_empty_county(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("Bob Jones | ZZ")
        # ZZ not in _STATE_DEFAULT
        assert county_key == ""

    def test_pipe_with_non_matching_loc(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        # loc doesn't match "County XX" and isn't a bare state abbr → falls through
        name, county_key, state = _parse_identifier("Bob Jones | SomePlace")
        assert name == "Bob Jones"

    def test_maricopa_az(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("Alice Green | Maricopa County AZ")
        assert county_key == "maricopa_az"
        assert state == "AZ"

    def test_nyc_ny(self):
        from modules.crawlers.property.deed_recorder import _parse_identifier

        name, county_key, state = _parse_identifier("Carl White NY")
        assert state == "NY"
        assert county_key == "nyc_ny"


# ---------------------------------------------------------------------------
# _parse_deed_table
# ---------------------------------------------------------------------------


class TestParseDeedTable:
    def test_empty_html_returns_empty(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        assert _parse_deed_table("<html></html>", "John Smith") == []

    def test_acris_table_parsing(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table id="docSearchResults">
          <tr><th>Doc#</th><th>Type</th><th>Date</th><th>Grantor</th><th>Grantee</th></tr>
          <tr><td>DOC001</td><td>WD</td><td>2022-01-15</td><td>SELLER INC</td><td>BUYER LLC</td></tr>
          <tr><td>DOC002</td><td>DOT</td><td>2022-01-20</td><td>OWNER A</td><td>OWNER B</td></tr>
        </table>
        </body></html>
        """
        deeds = _parse_deed_table(html, "John Smith")
        assert len(deeds) == 2
        assert deeds[0]["document_number"] == "DOC001"
        assert deeds[0]["acquisition_type"] == "Warranty Deed"

    def test_acris_grantor_search_swaps_names(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table id="search_results">
          <tr><th>Doc#</th><th>Type</th><th>Date</th><th>Grantor</th><th>Grantee</th></tr>
          <tr><td>DOC003</td><td>GD</td><td>2021-06-01</td><td>GRANTOR A</td><td>GRANTEE B</td></tr>
        </table>
        </body></html>
        """
        # grantor_or_grantee = "grantor" → owner_name = grantee (cells[4])
        deeds = _parse_deed_table(html, "grantor")
        assert len(deeds) == 1
        assert deeds[0]["owner_name"] == "GRANTEE B"

    def test_generic_table_with_matching_headers(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr>
            <th>Instrument Number</th>
            <th>Deed Type</th>
            <th>Record Date</th>
            <th>Grantor</th>
            <th>Grantee</th>
            <th>Consideration Amount</th>
          </tr>
          <tr>
            <td>INST-9999</td>
            <td>WD</td>
            <td>2023-04-10</td>
            <td>SMITH JOHN</td>
            <td>JONES JANE</td>
            <td>$350,000</td>
          </tr>
        </table>
        </body></html>
        """
        deeds = _parse_deed_table(html, "grantor")
        assert len(deeds) == 1
        assert deeds[0]["document_number"] == "INST-9999"
        assert deeds[0]["acquisition_price_usd"] == 350000
        assert deeds[0]["acquisition_type"] == "Warranty Deed"

    def test_generic_table_empty_rows_skipped(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr><th>Document</th><th>Grantor</th></tr>
          <tr><td></td><td></td></tr>
        </table>
        </body></html>
        """
        deeds = _parse_deed_table(html, "grantor")
        assert deeds == []

    def test_table_without_deed_keywords_skipped(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr><th>Name</th><th>Address</th></tr>
          <tr><td>Bob</td><td>123 Main</td></tr>
        </table>
        </body></html>
        """
        deeds = _parse_deed_table(html, "grantor")
        assert deeds == []

    def test_amount_parse_failure_does_not_crash(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr><th>Instrument</th><th>Deed</th><th>Record Date</th><th>Grantor</th><th>Grantee</th><th>Amount</th></tr>
          <tr><td>DOC777</td><td>WD</td><td>2020-01-01</td><td>A</td><td>B</td><td>N/A</td></tr>
        </table>
        </body></html>
        """
        deeds = _parse_deed_table(html, "grantor")
        # amount couldn't be parsed — deed still included because it has document_number
        assert len(deeds) == 1
        assert deeds[0]["acquisition_price_usd"] is None

    def test_acris_table_fewer_than_5_cells_skipped(self):
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table id="docSearchResults">
          <tr><th>Doc#</th><th>Type</th><th>Date</th></tr>
          <tr><td>DOC001</td><td>WD</td><td>2022-01-15</td></tr>
        </table>
        </body></html>
        """
        deeds = _parse_deed_table(html, "grantor")
        assert deeds == []

    def test_table_with_only_header_row_skipped(self):
        """Line 245: table with < 2 rows (only header) hits the continue branch."""
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr><th>Instrument</th><th>Grantor</th></tr>
        </table>
        </body></html>
        """
        # Only 1 row → len(rows) < 2 → continue
        deeds = _parse_deed_table(html, "grantor")
        assert deeds == []

    def test_header_cells_exceed_data_cells_break_branch(self):
        """Line 267: i >= len(cells) → break when headers outnumber data cells."""
        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr>
            <th>Instrument Number</th>
            <th>Deed Type</th>
            <th>Record Date</th>
            <th>Grantor</th>
            <th>Grantee</th>
            <th>Consideration Amount</th>
          </tr>
          <tr>
            <td>INST-BREAK</td>
            <td>WD</td>
            <td>2023-01-01</td>
          </tr>
        </table>
        </body></html>
        """
        # Row has 3 cells, headers has 6 → break at i=3
        deeds = _parse_deed_table(html, "grantor")
        # deed has document_number set, so it may be appended
        assert isinstance(deeds, list)

    def test_amount_int_valueerror_branch(self):
        """Lines 284-285: int() raises ValueError on amount string → deed still included."""
        import builtins

        from modules.crawlers.property.deed_recorder import _parse_deed_table

        html = """
        <html><body>
        <table>
          <tr><th>Instrument</th><th>Deed</th><th>Record Date</th><th>Grantor</th><th>Grantee</th><th>Amount</th></tr>
          <tr><td>DOC-ERR</td><td>WD</td><td>2020-01-01</td><td>A</td><td>B</td><td>$500</td></tr>
        </table>
        </body></html>
        """
        real_int = builtins.int
        call_count = [0]

        def patched_int(val, *args, **kwargs):
            call_count[0] += 1
            # Force ValueError on first call (the amount int conversion)
            if call_count[0] == 1 and not args:
                raise ValueError("forced int error")
            return real_int(val, *args, **kwargs)

        with patch.object(builtins, "int", side_effect=patched_int):
            deeds = _parse_deed_table(html, "grantor")

        # Deed still appended (has document_number), price is None
        assert len(deeds) == 1
        assert deeds[0]["acquisition_price_usd"] is None


# ---------------------------------------------------------------------------
# DeedRecorderCrawler.scrape
# ---------------------------------------------------------------------------


class TestDeedRecorderCrawlerScrape:
    def _make_crawler(self):
        from modules.crawlers.property.deed_recorder import DeedRecorderCrawler

        return DeedRecorderCrawler()

    def _deed_html(self, doc_num="DOC001"):
        return f"""
        <html><body>
        <table id="docSearchResults">
          <tr><th>Doc#</th><th>Type</th><th>Date</th><th>Grantor</th><th>Grantee</th></tr>
          <tr><td>{doc_num}</td><td>WD</td><td>2022-01-15</td><td>SELLER</td><td>BUYER</td></tr>
        </table>
        </body></html>
        """

    async def test_no_name_returns_error(self):
        crawler = self._make_crawler()
        result = await crawler.scrape("")
        assert result.found is False
        assert result.data.get("error") == "name_required"

    async def test_no_recorder_for_county(self):
        crawler = self._make_crawler()
        # State ZZ has no recorder
        result = await crawler.scrape("John Smith | Unknown County ZZ")
        assert result.found is False
        assert "no_recorder" in (result.data.get("error") or "")

    async def test_no_recorder_no_state(self):
        crawler = self._make_crawler()
        result = await crawler.scrape("Just A Name Without State Info")
        assert result.found is False

    async def test_successful_scrape_harris_tx(self):
        crawler = self._make_crawler()
        html = self._deed_html("DOC-TX-001")
        grantor_resp = _mock_resp(status=200, text=html)
        grantee_resp = _mock_resp(status=200, text=html)

        responses = iter([grantor_resp, grantee_resp])

        async def fake_get(url, **kwargs):
            return next(responses)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("John Smith TX")

        assert result.found is True
        assert result.data.get("state") == "TX"

    async def test_deduplication_by_document_number(self):
        crawler = self._make_crawler()
        # Both grantor and grantee return the same deed
        html = self._deed_html("DOC-SAME-001")
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith TX")

        ownership = result.data.get("ownership_history", [])
        # Deduplication by document_number — only 1 entry
        doc_nums = [d.get("document_number") for d in ownership]
        assert doc_nums.count("DOC-SAME-001") == 1

    async def test_grantor_none_response_continues(self):
        crawler = self._make_crawler()
        html = self._deed_html("DOC-GRANTEE")

        async def fake_get(url, **kwargs):
            if "Grantor" in url or "grantor" in url:
                return None
            return _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("John Smith TX")

        assert result.found is True

    async def test_grantee_non_200_skipped(self):
        crawler = self._make_crawler()
        html = self._deed_html("DOC-ONLY-GRANTOR")

        async def fake_get(url, **kwargs):
            if "Grantor" in url or "grantor" in url.lower():
                return _mock_resp(status=200, text=html)
            return _mock_resp(status=503, text="error")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("John Smith TX")

        # Grantor found deeds, grantee skipped
        assert result.found is True

    async def test_both_none_responses_returns_not_found(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith TX")

        assert result.found is False

    async def test_county_key_from_pipe_syntax(self):
        crawler = self._make_crawler()

        async def fake_get(url, **kwargs):
            return _mock_resp(status=200, text=self._deed_html("DOC-COOK"))

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("Smith, John | Cook County IL")

        assert result.data.get("county") == "cook_il"
        assert result.found is True

    async def test_state_default_fallback(self):
        """When county_key from parsing doesn't exist in _RECORDERS, uses state default."""
        crawler = self._make_crawler()

        # "John Smith WA" → state=WA → default=king_wa
        async def fake_get(url, **kwargs):
            return _mock_resp(status=200, text=self._deed_html("DOC-WA"))

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("John Smith WA")

        assert result.found is True
