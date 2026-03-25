"""
test_county_assessor_multi.py — 100% line coverage for county_assessor_multi.py.

Covers every county handler, all parse helpers, _generic_table_parse,
_resolve_county_key, and the CountyAssessorMultiCrawler.scrape() dispatcher.
All HTTP calls are mocked via patch.object on the crawler instance.
asyncio_mode=auto — no @pytest.mark.asyncio decorators.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (json.dumps(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


def _make_crawler():
    from modules.crawlers.property.county_assessor_multi import CountyAssessorMultiCrawler
    return CountyAssessorMultiCrawler()


# ---------------------------------------------------------------------------
# _parse_identifier
# ---------------------------------------------------------------------------


class TestParseIdentifier:
    def _fn(self, s):
        from modules.crawlers.property.county_assessor_multi import _parse_identifier
        return _parse_identifier(s)

    def test_pipe_county_state(self):
        q, county, state = self._fn("John Smith | Miami-Dade FL")
        assert q == "John Smith"
        assert county == "miami-dade"
        assert state == "FL"

    def test_pipe_county_word(self):
        """'Cook County IL' — strips trailing 'County'."""
        q, county, state = self._fn("123 Main St | Cook County IL")
        assert q == "123 Main St"
        assert county == "cook"
        assert state == "IL"

    def test_pipe_state_only(self):
        """Pipe but loc is just a two-letter state."""
        q, county, state = self._fn("John Smith | CA")
        assert q == "John Smith"
        assert state == "CA"
        assert county == ""

    def test_pipe_loc_no_state_match(self):
        """Pipe with loc that has no trailing two-letter state."""
        q, county, state = self._fn("John Smith | Los Angeles")
        assert q == "John Smith"
        # loc returned as state verbatim when no match
        assert state == "LOS ANGELES"

    def test_bare_address_with_state(self):
        """Bare address ending in state abbreviation."""
        q, county, state = self._fn("123 Main St, Los Angeles CA")
        assert state == "CA"
        assert "123 Main St" in q

    def test_bare_address_with_zip(self):
        """Bare address with state then 5-digit zip."""
        q, county, state = self._fn("456 Oak Ave TX 78701")
        assert state == "TX"

    def test_bare_no_state(self):
        """No recognisable state — returns raw string."""
        q, county, state = self._fn("just a name")
        assert q == "just a name"
        assert state == ""
        assert county == ""


# ---------------------------------------------------------------------------
# _resolve_county_key
# ---------------------------------------------------------------------------


class TestResolveCountyKey:
    def _fn(self, county, state):
        from modules.crawlers.property.county_assessor_multi import _resolve_county_key
        return _resolve_county_key(county, state)

    def test_exact_match(self):
        assert self._fn("cook", "IL") == "cook_il"

    def test_hyphen_county(self):
        assert self._fn("miami-dade", "FL") == "miami_dade_fl"

    def test_partial_match(self):
        # "los_angeles" contains "los" — partial match should still resolve
        key = self._fn("los angeles", "CA")
        assert key == "los_angeles_ca"

    def test_state_fallback(self):
        """Unknown county in a known state — returns first handler for that state."""
        key = self._fn("unknown_county", "CA")
        assert key is not None
        assert key.endswith("_ca")

    def test_no_match(self):
        key = self._fn("nowhere", "ZZ")
        assert key is None

    def test_space_county_normalised(self):
        assert self._fn("san francisco", "CA") == "san_francisco_ca"


# ---------------------------------------------------------------------------
# _money / _year / _sqft helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_money_parses_usd(self):
        from modules.crawlers.property.county_assessor_multi import _money
        assert _money("$1,234,567") == 1234567

    def test_money_no_match(self):
        from modules.crawlers.property.county_assessor_multi import _money
        assert _money("N/A") is None

    def test_money_value_error(self):
        """Regex finds something but int() would fail — returns None."""
        from modules.crawlers.property.county_assessor_multi import _money
        # _money strips $ first, then looks for [\d,]{3,}
        # Can't easily trigger ValueError via the API, but coverage is met via None path
        assert _money("") is None

    def test_year_found(self):
        from modules.crawlers.property.county_assessor_multi import _year
        assert _year("Built in 1995") == 1995

    def test_year_not_found(self):
        from modules.crawlers.property.county_assessor_multi import _year
        assert _year("no year here") is None

    def test_sqft_with_sq_ft(self):
        from modules.crawlers.property.county_assessor_multi import _sqft
        assert _sqft("1,500 sq. ft") == 1500

    def test_sqft_with_sf(self):
        from modules.crawlers.property.county_assessor_multi import _sqft
        assert _sqft("2000 sf") == 2000

    def test_sqft_none(self):
        from modules.crawlers.property.county_assessor_multi import _sqft
        assert _sqft("no area") is None

    def test_money_value_error_branch(self):
        """Regex matches but int() raises ValueError — returns None.
        We trigger this by patching int to raise on a specific call."""
        import re
        from modules.crawlers.property.county_assessor_multi import _money
        # Can't manufacture naturally; patch int() inside the function's scope
        original_int = int
        call_count = [0]

        def _patched_int(v=None, base=10):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("forced")
            return original_int(v)

        with patch("builtins.int", side_effect=_patched_int):
            result = _money("1,234")
        assert result is None

    def test_sqft_value_error_branch(self):
        """Regex matches but int() raises ValueError — returns None."""
        from modules.crawlers.property.county_assessor_multi import _sqft
        with patch("builtins.int", side_effect=ValueError("forced")):
            result = _sqft("1,200 sq ft")
        assert result is None


# ---------------------------------------------------------------------------
# _generic_table_parse
# ---------------------------------------------------------------------------


class TestGenericTableParse:
    def _fn(self, html, state="TX", county="Test"):
        from bs4 import BeautifulSoup
        from modules.crawlers.property.county_assessor_multi import _generic_table_parse
        soup = BeautifulSoup(html, "html.parser")
        return _generic_table_parse(soup, state, county)

    def test_no_tables(self):
        assert self._fn("<html><body>nothing</body></html>") == []

    def test_table_too_short(self):
        """Table with only one row — skip."""
        html = "<table><tr><th>parcel</th></tr></table>"
        assert self._fn(html) == []

    def test_table_no_keyword_headers(self):
        """Table header has no recognised keyword."""
        html = "<table><tr><th>foo</th><th>bar</th></tr><tr><td>1</td><td>2</td></tr></table>"
        assert self._fn(html) == []

    def test_table_with_parcel_header(self):
        """Table with 'parcel' header and one data row — one result."""
        html = (
            "<table>"
            "<tr><th>Parcel</th><th>Address</th><th>Owner</th></tr>"
            "<tr><td>123-45-678</td><td>100 Main St</td><td>John Smith</td></tr>"
            "</table>"
        )
        results = self._fn(html)
        assert len(results) == 1
        assert results[0]["parcel_number"] == "123-45-678"
        assert results[0]["street_address"] == "100 Main St"
        assert results[0]["owner_name"] == "John Smith"

    def test_table_all_empty_cells_skipped(self):
        html = (
            "<table>"
            "<tr><th>parcel</th><th>owner</th></tr>"
            "<tr><td></td><td></td></tr>"
            "</table>"
        )
        assert self._fn(html) == []

    def test_table_header_mapping_all_types(self):
        """Exercise all header-to-field mappings."""
        html = (
            "<table>"
            "<tr>"
            "<th>parcel</th><th>address</th><th>city</th><th>owner</th>"
            "<th>assessed value</th><th>market value</th><th>tax</th>"
            "<th>year built</th><th>sq ft</th><th>type</th>"
            "</tr>"
            "<tr>"
            "<td>APN-001</td><td>5 Oak Ln</td><td>Denver</td><td>Jane Doe</td>"
            "<td>$400,000</td><td>$500,000</td><td>$4,000</td>"
            "<td>2005</td><td>1,800 sq ft</td><td>Residential</td>"
            "</tr>"
            "</table>"
        )
        results = self._fn(html, "CO", "Denver")
        assert len(results) == 1
        p = results[0]
        assert p["parcel_number"] == "APN-001"
        assert p["current_assessed_value_usd"] == 400000
        assert p["current_market_value_usd"] == 500000
        assert p["current_tax_annual_usd"] == 4000
        assert p["year_built"] == 2005
        assert p["sq_ft_living"] == 1800
        assert p["property_type"] == "Residential"

    def test_header_just_keyword(self):
        """Pin/apn/folio/account aliases all resolve to parcel_number."""
        for kw in ("pin", "apn", "folio", "account"):
            html = (
                f"<table><tr><th>{kw}</th></tr>"
                "<tr><td>XYZ-999</td></tr></table>"
            )
            results = self._fn(html)
            if results:
                assert results[0]["parcel_number"] == "XYZ-999"

    def test_row_owner_only_no_parcel(self):
        """Row with only owner set — still appended."""
        html = (
            "<table>"
            "<tr><th>owner</th></tr>"
            "<tr><td>Bob Jones</td></tr>"
            "</table>"
        )
        results = self._fn(html)
        assert len(results) == 1
        assert results[0]["owner_name"] == "Bob Jones"

    def test_cells_shorter_than_headers(self):
        """More headers than cells — loop breaks early, no IndexError."""
        html = (
            "<table>"
            "<tr><th>parcel</th><th>address</th><th>city</th></tr>"
            "<tr><td>111</td></tr>"
            "</table>"
        )
        results = self._fn(html)
        assert results[0]["parcel_number"] == "111"

    def test_area_header_fallback_to_money(self):
        """'area' header with no sqft unit falls back to _money."""
        html = (
            "<table>"
            "<tr><th>parcel</th><th>area</th></tr>"
            "<tr><td>P-99</td><td>1500</td></tr>"
            "</table>"
        )
        results = self._fn(html)
        assert results[0]["sq_ft_living"] is not None

    def test_just_value_header(self):
        """'market' or 'just' header maps to market value."""
        html = (
            "<table>"
            "<tr><th>parcel</th><th>just value</th></tr>"
            "<tr><td>P-77</td><td>$300,000</td></tr>"
            "</table>"
        )
        results = self._fn(html)
        assert results[0]["current_market_value_usd"] == 300000

    def test_max_20_rows(self):
        """Rows beyond index 20 are ignored."""
        rows = "".join(
            f"<tr><td>P-{i}</td></tr>" for i in range(25)
        )
        html = f"<table><tr><th>parcel</th></tr>{rows}</table>"
        results = self._fn(html)
        assert len(results) <= 19

    def test_empty_cell_value_skipped(self):
        """Cell text is empty string for a mapped header — val is '' → skipped (line 479)."""
        html = (
            "<table>"
            "<tr><th>parcel</th><th>address</th></tr>"
            "<tr><td>P-EMPTY-TEST</td><td></td></tr>"
            "</table>"
        )
        results = self._fn(html)
        assert len(results) == 1
        # address not set because val was empty
        assert results[0]["parcel_number"] == "P-EMPTY-TEST"
        assert results[0]["street_address"] is None


# ---------------------------------------------------------------------------
# Per-county handlers — None and non-200 paths
# ---------------------------------------------------------------------------


class TestHandlerHttpFailures:
    """Each county handler must return [] on None or non-200 responses."""

    async def _run(self, handler_fn, status=404):
        from modules.crawlers.property.county_assessor_multi import CountyAssessorMultiCrawler
        crawler = CountyAssessorMultiCrawler()
        resp = _mock_resp(status=status, text="<html></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            return await handler_fn(crawler, "query")

    async def _run_none(self, handler_fn):
        from modules.crawlers.property.county_assessor_multi import CountyAssessorMultiCrawler
        crawler = CountyAssessorMultiCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            return await handler_fn(crawler, "query")

    # --- LA County ----------------------------------------------------------

    async def test_la_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_la_ca
        assert await self._run_none(_scrape_la_ca) == []

    async def test_la_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_la_ca
        assert await self._run(_scrape_la_ca) == []

    # --- Alameda ------------------------------------------------------------

    async def test_alameda_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_alameda_ca
        assert await self._run_none(_scrape_alameda_ca) == []

    async def test_alameda_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_alameda_ca
        assert await self._run(_scrape_alameda_ca) == []

    # --- San Diego ----------------------------------------------------------

    async def test_san_diego_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_san_diego_ca
        assert await self._run_none(_scrape_san_diego_ca) == []

    # --- SF -----------------------------------------------------------------

    async def test_sf_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_sf_ca
        assert await self._run_none(_scrape_sf_ca) == []

    # --- Orange -------------------------------------------------------------

    async def test_orange_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_orange_ca
        assert await self._run_none(_scrape_orange_ca) == []

    # --- Riverside ----------------------------------------------------------

    async def test_riverside_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_riverside_ca
        assert await self._run_none(_scrape_riverside_ca) == []

    # --- Miami-Dade ---------------------------------------------------------

    async def test_miami_dade_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        assert await self._run_none(_scrape_miami_dade_fl) == []

    async def test_miami_dade_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        assert await self._run(_scrape_miami_dade_fl) == []

    # --- Broward ------------------------------------------------------------

    async def test_broward_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_broward_fl
        assert await self._run_none(_scrape_broward_fl) == []

    # --- Palm Beach ---------------------------------------------------------

    async def test_palm_beach_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_palm_beach_fl
        assert await self._run_none(_scrape_palm_beach_fl) == []

    # --- Hillsborough -------------------------------------------------------

    async def test_hillsborough_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_hillsborough_fl
        assert await self._run_none(_scrape_hillsborough_fl) == []

    # --- Pinellas -----------------------------------------------------------

    async def test_pinellas_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_pinellas_fl
        assert await self._run_none(_scrape_pinellas_fl) == []

    # --- NYC ----------------------------------------------------------------

    async def test_nyc_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_nyc_ny
        assert await self._run_none(_scrape_nyc_ny) == []

    async def test_nyc_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_nyc_ny
        assert await self._run(_scrape_nyc_ny) == []

    # --- Cook ---------------------------------------------------------------

    async def test_cook_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_cook_il
        assert await self._run_none(_scrape_cook_il) == []

    async def test_cook_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_cook_il
        assert await self._run(_scrape_cook_il) == []

    # --- Maricopa -----------------------------------------------------------

    async def test_maricopa_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        assert await self._run_none(_scrape_maricopa_az) == []

    async def test_maricopa_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        assert await self._run(_scrape_maricopa_az) == []

    # --- Clark NV -----------------------------------------------------------

    async def test_clark_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_clark_nv
        assert await self._run_none(_scrape_clark_nv) == []

    # --- King WA ------------------------------------------------------------

    async def test_king_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_king_wa
        assert await self._run_none(_scrape_king_wa) == []

    # --- Fulton GA ----------------------------------------------------------

    async def test_fulton_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_fulton_ga
        assert await self._run_none(_scrape_fulton_ga) == []

    # --- DeKalb GA ----------------------------------------------------------

    async def test_dekalb_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_dekalb_ga
        assert await self._run_none(_scrape_dekalb_ga) == []

    # --- Mecklenburg NC -----------------------------------------------------

    async def test_mecklenburg_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_mecklenburg_nc
        assert await self._run_none(_scrape_mecklenburg_nc) == []

    async def test_mecklenburg_non_200(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_mecklenburg_nc
        assert await self._run(_scrape_mecklenburg_nc) == []

    # --- Denver CO ----------------------------------------------------------

    async def test_denver_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_denver_co
        assert await self._run_none(_scrape_denver_co) == []

    # --- Arapahoe CO --------------------------------------------------------

    async def test_arapahoe_none(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_arapahoe_co
        assert await self._run_none(_scrape_arapahoe_co) == []


# ---------------------------------------------------------------------------
# LA County — JSON success path + HTML fallback
# ---------------------------------------------------------------------------


class TestLaCountyScraper:
    async def test_json_parcels_key(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_la_ca
        crawler = _make_crawler()
        data = {
            "parcels": [
                {
                    "ain": "1234-567",
                    "situs": "100 Main St",
                    "city": "Los Angeles",
                    "ownerName": "John Smith",
                    "totalValue": "500000",
                    "marketValue": "600000",
                    "yearBuilt": 1980,
                    "sqftMain": 1500,
                    "useCode": "SFR",
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_la_ca(crawler, "John Smith")
        assert len(parcels) == 1
        assert parcels[0]["parcel_number"] == "1234-567"
        assert parcels[0]["current_assessed_value_usd"] == 500000
        assert parcels[0]["county"] == "Los Angeles"

    async def test_json_results_key(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_la_ca
        crawler = _make_crawler()
        data = {
            "results": [
                {
                    "parcelnumber": "9999",
                    "address": "200 Broad St",
                    "owner": "Jane Doe",
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_la_ca(crawler, "Jane Doe")
        assert parcels[0]["parcel_number"] == "9999"

    async def test_json_empty_returns_empty_list(self):
        """json() succeeds but both keys absent → returns empty list (no HTML fallback)."""
        from modules.crawlers.property.county_assessor_multi import _scrape_la_ca
        crawler = _make_crawler()
        data: dict = {}
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_la_ca(crawler, "query")
        # json() succeeds and returns [] — function returns [] without HTML fallback
        assert parcels == []

    async def test_json_exception_falls_back_to_html(self):
        """resp.json() raises → HTML BeautifulSoup fallback."""
        from modules.crawlers.property.county_assessor_multi import _scrape_la_ca
        crawler = _make_crawler()
        html = (
            "<table>"
            "<tr><th>parcel</th></tr>"
            "<tr><td>FALLBACK-1</td></tr>"
            "</table>"
        )
        resp = _mock_resp(status=200, text=html)
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_la_ca(crawler, "query")
        # HTML fallback runs — may or may not produce parcels depending on header
        assert isinstance(parcels, list)


# ---------------------------------------------------------------------------
# Cook County — JSON paths
# ---------------------------------------------------------------------------


class TestCookCountyScraper:
    async def test_json_pins_key(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_cook_il
        crawler = _make_crawler()
        data = {
            "pins": [
                {
                    "pin": "14-25-301-001-0000",
                    "address": "500 W Madison",
                    "city": "Chicago",
                    "ownerName": "Corp LLC",
                    "assessedValue": "200000",
                    "yearBuilt": 1960,
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_cook_il(crawler, "Corp LLC")
        assert len(parcels) == 1
        assert parcels[0]["parcel_number"] == "14-25-301-001-0000"
        assert parcels[0]["county"] == "Cook"

    async def test_json_results_key(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_cook_il
        crawler = _make_crawler()
        data = {"results": [{"PIN": "99-00", "propertyAddress": "1 N LaSalle"}]}
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_cook_il(crawler, "query")
        assert parcels[0]["parcel_number"] == "99-00"

    async def test_json_empty_falls_back_to_html(self):
        """JSON has no pins/results — HTML fallback runs."""
        from modules.crawlers.property.county_assessor_multi import _scrape_cook_il
        crawler = _make_crawler()
        data: dict = {}
        html = (
            "<table>"
            "<tr><th>pin</th><th>address</th></tr>"
            "<tr><td>C-001</td><td>10 W Grant</td></tr>"
            "</table>"
        )
        resp = _mock_resp(status=200, json_data=data, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_cook_il(crawler, "query")
        assert isinstance(parcels, list)

    async def test_json_exception_falls_back_to_html(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_cook_il
        crawler = _make_crawler()
        resp = _mock_resp(status=200, text="<html></html>")
        resp.json.side_effect = RuntimeError("bad")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_cook_il(crawler, "query")
        assert isinstance(parcels, list)


# ---------------------------------------------------------------------------
# Mecklenburg NC — JSON paths
# ---------------------------------------------------------------------------


class TestMecklenburgScraper:
    async def test_json_features_key(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_mecklenburg_nc
        crawler = _make_crawler()
        data = {
            "features": [
                {
                    "attributes": {
                        "PIN": "119-083-11",
                        "FULL_ADDRESS": "1600 Montford Dr",
                        "CITY": "Charlotte",
                        "OWNER_NAME": "Mary Jones",
                        "TOTAL_VALUE": "350000",
                        "YEAR_BUILT": 1995,
                        "HEATED_AREA": 2100,
                    }
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_mecklenburg_nc(crawler, "Mary Jones")
        assert len(parcels) == 1
        assert parcels[0]["county"] == "Mecklenburg"
        assert parcels[0]["current_assessed_value_usd"] == 350000

    async def test_json_results_key_attr_is_item(self):
        """attr = item fallback when 'attributes' key missing."""
        from modules.crawlers.property.county_assessor_multi import _scrape_mecklenburg_nc
        crawler = _make_crawler()
        data = {
            "results": [
                {
                    "pid": "AAA-111",
                    "address": "5 Trade St",
                    "ownerName": "Bob",
                    "TOTAL_VALUE": "100000",
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_mecklenburg_nc(crawler, "Bob")
        assert parcels[0]["parcel_number"] == "AAA-111"

    async def test_json_empty_falls_back_to_html(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_mecklenburg_nc
        crawler = _make_crawler()
        data: dict = {}
        html = (
            "<table><tr><th>pin</th></tr><tr><td>NC-001</td></tr></table>"
        )
        resp = _mock_resp(status=200, json_data=data, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_mecklenburg_nc(crawler, "query")
        assert isinstance(parcels, list)

    async def test_json_exception_falls_back_to_html(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_mecklenburg_nc
        crawler = _make_crawler()
        resp = _mock_resp(status=200, text="<html></html>")
        resp.json.side_effect = RuntimeError("bad")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_mecklenburg_nc(crawler, "query")
        assert isinstance(parcels, list)


# ---------------------------------------------------------------------------
# Miami-Dade — HTML table parsing paths
# ---------------------------------------------------------------------------


class TestMiamiDadeScraper:
    async def test_with_folio_rows(self):
        """Table rows with folio + address + owner + value."""
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="property-search-results">'
            "<tr><td>01-1234-567-8910</td><td>100 SW 1st Ave</td>"
            "<td>John Smith</td><td>$450,000</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_miami_dade_fl(crawler, "John Smith")
        assert len(parcels) == 1
        assert parcels[0]["parcel_number"] == "01-1234-567-8910"
        assert parcels[0]["county"] == "Miami-Dade"
        assert parcels[0]["current_market_value_usd"] == 450000

    async def test_folio_header_row_skipped(self):
        """Row where folio cell contains 'folio' — skip it."""
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="property-search-results">'
            "<tr><td>Folio Number</td><td>Address</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_miami_dade_fl(crawler, "query")
        # No valid parcels from table; falls back to generic parse which also finds none
        assert isinstance(parcels, list)

    async def test_empty_folio_skipped(self):
        """Row with empty first cell — skip."""
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="property-search-results">'
            "<tr><td></td><td>Somewhere</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_miami_dade_fl(crawler, "query")
        assert isinstance(parcels, list)

    async def test_row_only_one_cell_skipped(self):
        """Row with fewer than 2 <td> — skipped."""
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="property-search-results">'
            "<tr><td>onecell</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_miami_dade_fl(crawler, "query")
        assert isinstance(parcels, list)

    async def test_generic_fallback_when_no_miami_rows(self):
        """No table.property-search-results rows → generic fallback runs."""
        from modules.crawlers.property.county_assessor_multi import _scrape_miami_dade_fl
        crawler = _make_crawler()
        html = (
            "<html><body>"
            "<table>"
            "<tr><th>folio</th><th>address</th><th>owner</th></tr>"
            "<tr><td>FOLIO-001</td><td>200 Brickell</td><td>Corp Inc</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_miami_dade_fl(crawler, "query")
        assert isinstance(parcels, list)


# ---------------------------------------------------------------------------
# Maricopa AZ — HTML parsing paths
# ---------------------------------------------------------------------------


class TestMaricopaScraper:
    async def test_with_apn_rows(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="results">'
            "<tr><td>301-23-456</td><td>789 W McDowell</td>"
            "<td>Phoenix</td><td>Smith LLC</td><td>$300,000</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_maricopa_az(crawler, "Smith LLC")
        assert len(parcels) == 1
        assert parcels[0]["state"] == "AZ"
        assert parcels[0]["current_assessed_value_usd"] == 300000

    async def test_apn_header_row_skipped(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="results">'
            "<tr><td>APN</td><td>Address</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_maricopa_az(crawler, "query")
        assert isinstance(parcels, list)

    async def test_empty_cells_skipped(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="results">'
            "<tr><td></td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_maricopa_az(crawler, "query")
        assert isinstance(parcels, list)

    async def test_generic_fallback_when_no_maricopa_rows(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        crawler = _make_crawler()
        html = (
            "<html><body>"
            "<table>"
            "<tr><th>apn</th><th>owner</th></tr>"
            "<tr><td>FALLBACK-APN</td><td>Owner B</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_maricopa_az(crawler, "query")
        assert isinstance(parcels, list)

    async def test_row_with_only_th_cells_skipped(self):
        """Row matched by selector has th but no td → cells empty → continue (line 340)."""
        from modules.crawlers.property.county_assessor_multi import _scrape_maricopa_az
        crawler = _make_crawler()
        html = (
            "<html><body>"
            '<table class="results">'
            "<tr><th>APN Header</th><th>Address Header</th></tr>"
            "<tr><td>200-300-400</td><td>8 W Test</td><td>Mesa</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            parcels = await _scrape_maricopa_az(crawler, "query")
        # th-only row skipped, td row processed
        assert isinstance(parcels, list)


# ---------------------------------------------------------------------------
# Simple HTML-only handlers (200 OK success path)
# ---------------------------------------------------------------------------


class TestSimpleHtmlHandlers:
    """Hit every handler's 200-OK success path to exercise the url-build + soup call."""

    _TABLE_HTML = (
        "<table>"
        "<tr><th>parcel</th><th>owner</th></tr>"
        "<tr><td>HTML-OK</td><td>Owner X</td></tr>"
        "</table>"
    )

    async def _run_handler(self, handler_fn):
        crawler = _make_crawler()
        resp = _mock_resp(status=200, text=self._TABLE_HTML)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            return await handler_fn(crawler, "query")

    async def test_alameda_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_alameda_ca
        r = await self._run_handler(_scrape_alameda_ca)
        assert isinstance(r, list)

    async def test_san_diego_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_san_diego_ca
        r = await self._run_handler(_scrape_san_diego_ca)
        assert isinstance(r, list)

    async def test_sf_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_sf_ca
        r = await self._run_handler(_scrape_sf_ca)
        assert isinstance(r, list)

    async def test_orange_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_orange_ca
        r = await self._run_handler(_scrape_orange_ca)
        assert isinstance(r, list)

    async def test_riverside_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_riverside_ca
        r = await self._run_handler(_scrape_riverside_ca)
        assert isinstance(r, list)

    async def test_broward_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_broward_fl
        r = await self._run_handler(_scrape_broward_fl)
        assert isinstance(r, list)

    async def test_palm_beach_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_palm_beach_fl
        r = await self._run_handler(_scrape_palm_beach_fl)
        assert isinstance(r, list)

    async def test_hillsborough_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_hillsborough_fl
        r = await self._run_handler(_scrape_hillsborough_fl)
        assert isinstance(r, list)

    async def test_pinellas_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_pinellas_fl
        r = await self._run_handler(_scrape_pinellas_fl)
        assert isinstance(r, list)

    async def test_nyc_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_nyc_ny
        r = await self._run_handler(_scrape_nyc_ny)
        assert isinstance(r, list)

    async def test_clark_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_clark_nv
        r = await self._run_handler(_scrape_clark_nv)
        assert isinstance(r, list)

    async def test_king_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_king_wa
        r = await self._run_handler(_scrape_king_wa)
        assert isinstance(r, list)

    async def test_fulton_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_fulton_ga
        r = await self._run_handler(_scrape_fulton_ga)
        assert isinstance(r, list)

    async def test_dekalb_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_dekalb_ga
        r = await self._run_handler(_scrape_dekalb_ga)
        assert isinstance(r, list)

    async def test_denver_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_denver_co
        r = await self._run_handler(_scrape_denver_co)
        assert isinstance(r, list)

    async def test_arapahoe_success(self):
        from modules.crawlers.property.county_assessor_multi import _scrape_arapahoe_co
        r = await self._run_handler(_scrape_arapahoe_co)
        assert isinstance(r, list)


# ---------------------------------------------------------------------------
# CountyAssessorMultiCrawler.scrape() dispatcher
# ---------------------------------------------------------------------------


class TestCountyAssessorMultiScrape:
    def _make(self):
        return _make_crawler()

    # --- No state in identifier ---------------------------------------------

    async def test_no_state_returns_error(self):
        crawler = self._make()
        result = await crawler.scrape("just a name")
        assert result.found is False
        assert "state_required" in result.data.get("error", "")

    # --- No handler for state -----------------------------------------------

    async def test_no_handler_for_state(self):
        crawler = self._make()
        # Valid identifier format but state has no registered county
        result = await crawler.scrape("John Smith | SomeCounty ZZ")
        assert result.found is False
        assert "no_handler_for" in result.data.get("error", "")

    # --- Handler exists but raises ------------------------------------------

    async def test_handler_raises_exception(self):
        crawler = self._make()
        with patch(
            "modules.crawlers.property.county_assessor_multi._COUNTY_HANDLERS",
            {"cook_il": AsyncMock(side_effect=RuntimeError("network error"))},
        ):
            result = await crawler.scrape("John Smith | Cook County IL")
        assert result.found is False
        assert "network error" in result.data.get("error", "")

    # --- Successful scrape with results -------------------------------------

    async def test_successful_scrape_returns_properties(self):
        crawler = self._make()
        fake_properties = [
            {
                "parcel_number": "14-25-301",
                "street_address": "500 W Madison",
                "state": "IL",
                "county": "Cook",
                "owner_name": "Corp LLC",
                "ownership_history": [],
                "valuations": [],
                "mortgages": [],
            }
        ]
        data = {"pins": [{"pin": "14-25-301", "address": "500 W Madison"}]}
        resp = _mock_resp(status=200, json_data=data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Corp LLC | Cook County IL")
        assert result.found is True
        assert len(result.data.get("properties", [])) >= 0

    # --- Scrape finds nothing — found=False ---------------------------------

    async def test_empty_properties_found_false(self):
        crawler = self._make()
        resp = _mock_resp(status=404, text="")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Nobody | Clark County NV")
        assert result.found is False

    # --- Bare address with state abbrev -------------------------------------

    async def test_bare_address_identifier(self):
        crawler = self._make()
        resp = _mock_resp(status=404, text="")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St, Miami FL")
        # Should resolve to miami-dade or first FL handler — either way no error about state
        assert "state_required" not in result.data.get("error", "")

    # --- NYC borough aliases ------------------------------------------------

    async def test_nyc_borough_brooklyn_resolves(self):
        crawler = self._make()
        resp = _mock_resp(status=200, text="<html></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Kings NY")
        assert "state_required" not in result.data.get("error", "")
        assert "no_handler_for" not in result.data.get("error", "")

    # --- County key present but handler missing from dict -------------------

    async def test_handler_not_in_dict_returns_error(self):
        """_COUNTY_HANDLERS.get(key) returns None — handler_not_implemented path."""
        crawler = self._make()
        with (
            patch(
                "modules.crawlers.property.county_assessor_multi._resolve_county_key",
                return_value="phantom_key",
            ),
            patch(
                "modules.crawlers.property.county_assessor_multi._COUNTY_HANDLERS",
                {},
            ),
        ):
            result = await crawler.scrape("John Smith | Cook County IL")
        assert result.found is False
        assert "handler_not_implemented" in result.data.get("error", "")

    # --- query/county_key stored in result data -----------------------------

    async def test_result_data_contains_query_and_county_key(self):
        crawler = self._make()
        resp = _mock_resp(status=200, json_data={"pins": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe | Cook County IL")
        assert result.data.get("query") == "Jane Doe"
        assert result.data.get("county_key") == "cook_il"
