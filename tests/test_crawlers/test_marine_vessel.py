"""
test_marine_vessel.py — Full branch coverage for marine_vessel.py.

Covers:
- _estimate_value(): tanker/bulk/container/cargo/yacht/fishing/passenger/tug/default,
  GT > 50000 multiplier, GT > 10000 multiplier, invalid GT, zero GT
- _is_vessel_search(): True / False
- _extract_vessel_name(): vessel: prefix stripped, owner passthrough
- _normalise_mt_item(): all key aliases, fallbacks
- _parse_marinetraffic_html(): table path, JSON-in-script path, no-table empty, invalid HTML
- _parse_vesselfinder_html(): table with rows, no table, < 2 rows, missing name skip
- _parse_uscg_html(): table with vessel keywords, table without keywords, < 2 rows, name+doc logic
- MarineVesselCrawler.scrape(): vessel_name mode, owner_name mode, dedup, empty
- _search_marinetraffic(): 200, 206, None, non-200
- _search_vesselfinder(): 200, 206, None, non-200
- _search_uscg(): vessel_name branch, owner_name branch, None, non-200
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.result import CrawlerResult
from modules.crawlers.transport.marine_vessel import (
    MarineVesselCrawler,
    _estimate_value,
    _extract_vessel_name,
    _is_vessel_search,
    _normalise_mt_item,
    _parse_marinetraffic_html,
    _parse_uscg_html,
    _parse_vesselfinder_html,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _crawler() -> MarineVesselCrawler:
    return MarineVesselCrawler()


# ---------------------------------------------------------------------------
# _estimate_value
# ---------------------------------------------------------------------------


def test_estimate_value_tanker_default_gt():
    assert _estimate_value("Tanker", 0) == 50_000_000


def test_estimate_value_bulk_carrier():
    assert _estimate_value("Bulk Carrier", None) == 30_000_000


def test_estimate_value_container():
    assert _estimate_value("Container Ship", 0) == 80_000_000


def test_estimate_value_cargo():
    assert _estimate_value("Cargo Vessel", 0) == 20_000_000


def test_estimate_value_yacht():
    assert _estimate_value("Luxury Yacht", 0) == 5_000_000


def test_estimate_value_fishing():
    assert _estimate_value("Fishing Vessel", 0) == 2_000_000


def test_estimate_value_passenger():
    assert _estimate_value("Passenger Ferry", 0) == 100_000_000


def test_estimate_value_tug():
    assert _estimate_value("Tug", 0) == 5_000_000


def test_estimate_value_default_type():
    assert _estimate_value("Unknown Class", 0) == 10_000_000


def test_estimate_value_gt_above_50000():
    base = _estimate_value("Tanker", 0)
    large = _estimate_value("Tanker", 60000)
    assert large == int(base * 2.5)


def test_estimate_value_gt_above_10000():
    base = _estimate_value("Cargo", 0)
    medium = _estimate_value("Cargo", 15000)
    assert medium == int(base * 1.5)


def test_estimate_value_invalid_gt_string():
    # ValueError on int() conversion — falls through, base unchanged
    assert _estimate_value("Tanker", "not_a_number") == 50_000_000


def test_estimate_value_none_gt():
    assert _estimate_value("Tanker", None) == 50_000_000


def test_estimate_value_empty_type():
    # No keyword match — default base
    assert _estimate_value("", 0) == 10_000_000


# ---------------------------------------------------------------------------
# _is_vessel_search
# ---------------------------------------------------------------------------


def test_is_vessel_search_with_prefix():
    assert _is_vessel_search("vessel:OCEAN QUEEN") is True


def test_is_vessel_search_uppercase_prefix():
    assert _is_vessel_search("VESSEL:Liberty") is True


def test_is_vessel_search_owner_name():
    assert _is_vessel_search("John Smith") is False


def test_is_vessel_search_empty():
    assert _is_vessel_search("") is False


# ---------------------------------------------------------------------------
# _extract_vessel_name
# ---------------------------------------------------------------------------


def test_extract_vessel_name_strips_prefix():
    assert _extract_vessel_name("vessel:OCEAN QUEEN") == "OCEAN QUEEN"


def test_extract_vessel_name_owner_passthrough():
    assert _extract_vessel_name("John Smith") == "John Smith"


def test_extract_vessel_name_strips_whitespace():
    assert _extract_vessel_name("  John Smith  ") == "John Smith"


def test_extract_vessel_name_vessel_with_spaces():
    assert _extract_vessel_name("vessel:  The Wanderer  ") == "The Wanderer"


# ---------------------------------------------------------------------------
# _normalise_mt_item
# ---------------------------------------------------------------------------


def test_normalise_mt_item_uppercase_keys():
    item = {
        "MMSI": "123456789",
        "IMO": "9876543",
        "SHIPNAME": "SEA WOLF",
        "CALLSIGN": "SW1",
        "FLAG": "PA",
        "TYPE_NAME": "Tanker",
        "GT": 75000,
        "LENGTH": 300,
        "YEAR_BUILT": 2005,
        "OWNER": "Wolf Corp",
        "MANAGER": "Wolf Ops",
        "PORT": "Panama City",
        "LAST_PORT": "Rotterdam",
        "LAT": 5.123,
        "LON": 80.456,
        "TIMESTAMP": "2026-03-25T10:00:00Z",
    }
    result = _normalise_mt_item(item)
    assert result["mmsi"] == "123456789"
    assert result["imo_number"] == "9876543"
    assert result["vessel_name"] == "SEA WOLF"
    assert result["flag_country"] == "PA"
    assert result["vessel_type"] == "Tanker"
    assert result["gross_tonnage"] == 75000
    assert result["owner_name"] == "Wolf Corp"
    assert result["operator_name"] == "Wolf Ops"
    assert result["last_seen_lat"] == 5.123
    assert result["source"] == "marinetraffic"
    # GT > 50000 → value multiplied
    assert result["estimated_value_usd"] == int(50_000_000 * 2.5)


def test_normalise_mt_item_lowercase_fallback_keys():
    item = {
        "mmsi": "999",
        "imo": "888",
        "vessel_name": "Fallback Ship",
        "call_sign": "FS",
        "flag": "LR",
        "type": "cargo",
        "gross_tonnage": 5000,
        "length": 150,
        "year_built": 1995,
        "owner_name": "Owner LLC",
        "operator_name": "Op Inc",
        "port_of_registry": "Monrovia",
        "last_port": "Hamburg",
        "lat": None,
        "lon": None,
        "last_seen_at": "",
    }
    result = _normalise_mt_item(item)
    assert result["mmsi"] == "999"
    assert result["vessel_name"] == "Fallback Ship"


def test_normalise_mt_item_empty_item():
    result = _normalise_mt_item({})
    assert result["mmsi"] == ""
    assert result["vessel_name"] == ""
    assert result["source"] == "marinetraffic"


# ---------------------------------------------------------------------------
# _parse_marinetraffic_html — table path
# ---------------------------------------------------------------------------

_MT_TABLE_HTML = """
<html><body>
<table>
  <tr>
    <th>Vessel Name</th><th>MMSI</th><th>IMO</th>
    <th>Flag</th><th>Vessel Type</th><th>GT</th>
  </tr>
  <tr>
    <td>SEA WOLF</td><td>123456789</td><td>9999999</td>
    <td>PA</td><td>Tanker</td><td>80000</td>
  </tr>
</table>
</body></html>
"""

_MT_TABLE_NO_VESSEL_KW = """
<html><body>
<table>
  <tr><th>Color</th><th>Size</th></tr>
  <tr><td>Red</td><td>Large</td></tr>
</table>
</body></html>
"""


def test_parse_mt_html_table_success():
    vessels = _parse_marinetraffic_html(_MT_TABLE_HTML)
    assert len(vessels) == 1
    v = vessels[0]
    assert v["vessel_name"] == "SEA WOLF"
    assert v["mmsi"] == "123456789"
    assert v["source"] == "marinetraffic"
    assert v["is_active"] is True


def test_parse_mt_html_table_no_vessel_keyword_skipped():
    vessels = _parse_marinetraffic_html(_MT_TABLE_NO_VESSEL_KW)
    assert vessels == []


def test_parse_mt_html_table_skips_row_without_name():
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th><th>MMSI</th></tr>
      <tr><td></td><td>123</td></tr>
    </table>
    </body></html>
    """
    vessels = _parse_marinetraffic_html(html)
    assert vessels == []


def test_parse_mt_html_empty():
    vessels = _parse_marinetraffic_html("")
    assert vessels == []


def test_parse_mt_html_no_table():
    vessels = _parse_marinetraffic_html("<html><body><p>No table</p></body></html>")
    assert vessels == []


def test_parse_mt_html_table_single_row_skipped():
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th><th>MMSI</th></tr>
    </table>
    </body></html>
    """
    # Only header row — no data rows
    vessels = _parse_marinetraffic_html(html)
    assert vessels == []


# ---------------------------------------------------------------------------
# _parse_vesselfinder_html
# ---------------------------------------------------------------------------

_VF_HTML = """
<html><body>
<table class="ships-list">
  <tr>
    <th>Vessel Name</th><th>MMSI</th><th>IMO</th>
    <th>Flag</th><th>Type</th><th>GT</th>
  </tr>
  <tr>
    <td>LIBERTY</td><td>111222333</td><td>1234567</td>
    <td>BS</td><td>Cargo</td><td>12000</td>
  </tr>
</table>
</body></html>
"""


def test_parse_vf_html_success():
    vessels = _parse_vesselfinder_html(_VF_HTML)
    assert len(vessels) == 1
    v = vessels[0]
    assert v["vessel_name"] == "LIBERTY"
    assert v["source"] == "vesselfinder"
    assert v["is_active"] is True


def test_parse_vf_html_no_table():
    vessels = _parse_vesselfinder_html("<html><body><p>nothing</p></body></html>")
    assert vessels == []


def test_parse_vf_html_table_too_few_rows():
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th></tr>
    </table>
    </body></html>
    """
    vessels = _parse_vesselfinder_html(html)
    assert vessels == []


def test_parse_vf_html_skips_row_without_name():
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th><th>MMSI</th></tr>
      <tr><td></td><td>000</td></tr>
    </table>
    </body></html>
    """
    vessels = _parse_vesselfinder_html(html)
    assert vessels == []


def test_parse_vf_html_empty_string():
    vessels = _parse_vesselfinder_html("")
    assert vessels == []


# ---------------------------------------------------------------------------
# _parse_uscg_html
# ---------------------------------------------------------------------------

_USCG_HTML = """
<html><body>
<table>
  <tr>
    <th>Vessel Name</th><th>Document Number</th>
    <th>Owner</th><th>Vessel Type</th><th>Gross Tons</th>
    <th>Call Sign</th><th>Hailing Port</th>
  </tr>
  <tr>
    <td>USCG BOAT</td><td>DOC-001</td>
    <td>Govt Owner</td><td>Patrol</td><td>500</td>
    <td>KXYZ</td><td>Miami</td>
  </tr>
</table>
</body></html>
"""


def test_parse_uscg_html_success():
    vessels = _parse_uscg_html(_USCG_HTML)
    assert len(vessels) == 1
    v = vessels[0]
    assert v["vessel_name"] == "USCG BOAT"
    assert v["document_number"] == "DOC-001"
    assert v["source"] == "uscg_nvdc"
    assert v["flag_country"] == "US"
    assert v["owner_name"] == "Govt Owner"


def test_parse_uscg_html_no_vessel_keyword_in_headers():
    html = """
    <html><body>
    <table>
      <tr><th>Color</th><th>Size</th></tr>
      <tr><td>Blue</td><td>Large</td></tr>
    </table>
    </body></html>
    """
    vessels = _parse_uscg_html(html)
    assert vessels == []


def test_parse_uscg_html_too_few_rows():
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th></tr>
    </table>
    </body></html>
    """
    vessels = _parse_uscg_html(html)
    assert vessels == []


def test_parse_uscg_html_no_name_and_no_doc_skipped():
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th><th>Document Number</th><th>Owner</th></tr>
      <tr><td></td><td></td><td>Some Owner</td></tr>
    </table>
    </body></html>
    """
    vessels = _parse_uscg_html(html)
    assert vessels == []


def test_parse_uscg_html_doc_number_without_name():
    """A row with only a document number (no vessel name) should still be included."""
    html = """
    <html><body>
    <table>
      <tr><th>Vessel Name</th><th>Document Number</th><th>Owner</th></tr>
      <tr><td></td><td>DOC-999</td><td>Owner Inc</td></tr>
    </table>
    </body></html>
    """
    vessels = _parse_uscg_html(html)
    assert len(vessels) == 1
    assert vessels[0]["document_number"] == "DOC-999"


def test_parse_uscg_html_empty():
    vessels = _parse_uscg_html("")
    assert vessels == []


# ---------------------------------------------------------------------------
# MarineVesselCrawler.scrape()
# ---------------------------------------------------------------------------


async def test_scrape_vessel_name_search():
    crawler = _crawler()
    vessel = {
        "mmsi": "111",
        "imo_number": "222",
        "vessel_name": "SEA WOLF",
        "call_sign": "SW",
        "flag_country": "PA",
        "vessel_type": "Tanker",
        "gross_tonnage": 60000,
        "length_meters": 300,
        "year_built": 2000,
        "owner_name": "Owner",
        "operator_name": "Op",
        "port_of_registry": "Panama",
        "last_port": "Rotterdam",
        "last_seen_lat": None,
        "last_seen_lon": None,
        "last_seen_at": "",
        "is_active": True,
        "estimated_value_usd": 125_000_000,
        "source": "marinetraffic",
    }
    with (
        patch.object(crawler, "_search_marinetraffic", new=AsyncMock(return_value=[vessel])),
        patch.object(crawler, "_search_vesselfinder", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_uscg", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("vessel:SEA WOLF")

    assert isinstance(result, CrawlerResult)
    assert result.found is True
    assert result.data["search_type"] == "vessel_name"
    assert result.data["query"] == "SEA WOLF"
    assert result.data["vessel_count"] == 1


async def test_scrape_owner_name_search():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_marinetraffic", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_vesselfinder", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_uscg", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("John Smith")

    assert result.data["search_type"] == "owner_name"
    assert result.data["query"] == "John Smith"


async def test_scrape_deduplicates_by_vessel_mmsi():
    crawler = _crawler()
    vessel = {
        "mmsi": "111",
        "imo_number": "222",
        "vessel_name": "sea wolf",
        "call_sign": "",
        "flag_country": "PA",
        "vessel_type": "Tanker",
        "gross_tonnage": 0,
        "length_meters": "",
        "year_built": "",
        "owner_name": "",
        "operator_name": "",
        "port_of_registry": "",
        "last_port": "",
        "last_seen_lat": None,
        "last_seen_lon": None,
        "last_seen_at": "",
        "is_active": True,
        "estimated_value_usd": 50_000_000,
        "source": "marinetraffic",
    }
    with (
        patch.object(crawler, "_search_marinetraffic", new=AsyncMock(return_value=[vessel])),
        patch.object(crawler, "_search_vesselfinder", new=AsyncMock(return_value=[vessel])),
        patch.object(crawler, "_search_uscg", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("vessel:SEA WOLF")

    assert result.data["vessel_count"] == 1


async def test_scrape_empty_results():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_marinetraffic", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_vesselfinder", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_uscg", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("vessel:GHOST SHIP")

    assert result.found is False
    assert result.data["vessel_count"] == 0


# ---------------------------------------------------------------------------
# _search_marinetraffic — branches
# ---------------------------------------------------------------------------


async def test_search_mt_200():
    crawler = _crawler()
    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=_MT_TABLE_HTML))
    ):
        results = await crawler._search_marinetraffic("SEA+WOLF")
    assert isinstance(results, list)


async def test_search_mt_206_partial():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(206, text=""))):
        results = await crawler._search_marinetraffic("X")
    assert results == []


async def test_search_mt_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_marinetraffic("X")
    assert results == []


async def test_search_mt_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        results = await crawler._search_marinetraffic("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_vesselfinder — branches
# ---------------------------------------------------------------------------


async def test_search_vf_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=_VF_HTML))):
        results = await crawler._search_vesselfinder("LIBERTY")
    assert isinstance(results, list)


async def test_search_vf_206_partial():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(206, text=""))):
        results = await crawler._search_vesselfinder("X")
    assert results == []


async def test_search_vf_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_vesselfinder("X")
    assert results == []


async def test_search_vf_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
        results = await crawler._search_vesselfinder("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_uscg — branches (vessel_name vs owner_name URL logic)
# ---------------------------------------------------------------------------


async def test_search_uscg_vessel_name_mode():
    crawler = _crawler()
    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=_USCG_HTML))
    ) as mock_get:
        await crawler._search_uscg("SEA+WOLF", "vessel_name")
    # URL should have query as vessel name, owner_query empty
    call_url = mock_get.call_args[0][0]
    assert "VesselName=SEA+WOLF" in call_url
    assert "Owner=" in call_url


async def test_search_uscg_owner_name_mode():
    crawler = _crawler()
    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text="<html></html>"))
    ) as mock_get:
        await crawler._search_uscg("John+Smith", "owner_name")
    call_url = mock_get.call_args[0][0]
    assert "Owner=John+Smith" in call_url


async def test_search_uscg_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_uscg("X", "vessel_name")
    assert results == []


async def test_search_uscg_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        results = await crawler._search_uscg("X", "vessel_name")
    assert results == []


# ---------------------------------------------------------------------------
# _parse_marinetraffic_html — JSON-in-script extraction (lines 113-126)
# ---------------------------------------------------------------------------


def test_parse_mt_html_json_in_script_extracted():
    """Lines 112-126: when a <script> contains 'mmsi', extract JSON array from it."""
    # Build HTML with embedded script containing MMSI JSON data
    html = """
    <html><body>
    <script>
    var vessels = [{"MMSI": "123456789", "SHIPNAME": "SCRIPT SHIP", "FLAG": "PA",
                    "TYPE_NAME": "Tanker", "GT": 5000, "IMO": "1111111",
                    "CALLSIGN": "SS1", "LENGTH": 200, "YEAR_BUILT": 2010,
                    "OWNER": "Script Owner", "MANAGER": "Script Ops",
                    "PORT": "Panama", "LAST_PORT": "Rotterdam",
                    "LAT": 8.99, "LON": -79.5, "TIMESTAMP": "2026-03-25T00:00:00Z"}]
    </script>
    </body></html>
    """
    vessels = _parse_marinetraffic_html(html)
    assert len(vessels) == 1
    v = vessels[0]
    assert v["mmsi"] == "123456789"
    assert v["vessel_name"] == "SCRIPT SHIP"
    assert v["source"] == "marinetraffic"


def test_parse_mt_html_json_in_script_uppercase_mmsi_key():
    """Script text containing 'MMSI' (uppercase) also triggers JSON extraction."""
    html = """
    <html><body>
    <script>
    var data = [{"MMSI": "987654321", "SHIPNAME": "UPPER KEY SHIP", "FLAG": "LR",
                 "TYPE_NAME": "Cargo", "GT": 3000}]
    </script>
    </body></html>
    """
    vessels = _parse_marinetraffic_html(html)
    assert len(vessels) >= 1
    assert vessels[0]["mmsi"] == "987654321"


def test_parse_mt_html_json_in_script_malformed_json_skipped():
    """Lines 124-125: malformed JSON inside mmsi-containing script is silently skipped."""
    html = """
    <html><body>
    <script>
    var broken = "mmsi" + [{INVALID JSON HERE}];
    </script>
    </body></html>
    """
    # Should not raise; returns empty list or falls through to table path
    vessels = _parse_marinetraffic_html(html)
    assert isinstance(vessels, list)


def test_parse_mt_html_json_in_script_break_after_first_match():
    """Line 126: loop breaks after first matching script, second mmsi script is ignored."""
    html = """
    <html><body>
    <script>
    var first = [{"MMSI": "111111111", "SHIPNAME": "FIRST SHIP", "FLAG": "PA",
                  "TYPE_NAME": "Tanker", "GT": 1000}]
    </script>
    <script>
    var second = [{"MMSI": "222222222", "SHIPNAME": "SECOND SHIP", "FLAG": "MH",
                   "TYPE_NAME": "Bulk Carrier", "GT": 2000}]
    </script>
    </body></html>
    """
    vessels = _parse_marinetraffic_html(html)
    mmsi_list = [v["mmsi"] for v in vessels]
    assert "111111111" in mmsi_list
    assert "222222222" not in mmsi_list


# ---------------------------------------------------------------------------
# _normalise_mt_item — VESSEL_TYPE alias and GROSS_TONNAGE alias (line 184-185)
# ---------------------------------------------------------------------------


def test_normalise_mt_item_vessel_type_alias():
    """Line 184: VESSEL_TYPE key (not TYPE_NAME) is used when TYPE_NAME absent."""
    item = {
        "MMSI": "555",
        "VESSEL_TYPE": "Bulk Carrier",
        "GT": 12000,
    }
    result = _normalise_mt_item(item)
    assert result["vessel_type"] == "Bulk Carrier"
    # GT 12000 → 10k < gt < 50k multiplier applied: int(30_000_000 * 1.5)
    assert result["estimated_value_usd"] == int(30_000_000 * 1.5)


def test_normalise_mt_item_gross_tonnage_alias():
    """Line 185: GROSS_TONNAGE key is used when GT and gross_tonnage are absent."""
    item = {
        "mmsi": "777",
        "GROSS_TONNAGE": 60000,
        "TYPE_NAME": "Tanker",
    }
    result = _normalise_mt_item(item)
    assert result["gross_tonnage"] == 60000
    assert result["estimated_value_usd"] == int(50_000_000 * 2.5)


# ---------------------------------------------------------------------------
# _parse_vesselfinder_html — exception path (lines 265-266)
# ---------------------------------------------------------------------------


def test_parse_vf_html_exception_returns_empty_list():
    """Lines 265-266: exception inside _parse_vesselfinder_html is caught, returns []."""
    from unittest.mock import MagicMock, patch

    # Patch BeautifulSoup at the bs4 module level (imported inline inside the function)
    bad_soup = MagicMock()
    bad_soup.find.side_effect = RuntimeError("simulated parse failure")

    with patch("bs4.BeautifulSoup", return_value=bad_soup):
        vessels = _parse_vesselfinder_html("<html><body></body></html>")

    assert vessels == []


# ---------------------------------------------------------------------------
# _parse_uscg_html — break-after-first-table-with-vessels branch (lines 324-325)
# ---------------------------------------------------------------------------


def test_parse_uscg_html_breaks_after_first_vessel_table():
    """Lines 324-325: once a table yields vessels, the outer loop breaks."""
    html = """
    <html><body>
    <table id="first">
      <tr><th>Vessel Name</th><th>Document Number</th><th>Owner</th></tr>
      <tr><td>FIRST BOAT</td><td>DOC-001</td><td>Owner A</td></tr>
    </table>
    <table id="second">
      <tr><th>Vessel Name</th><th>Document Number</th><th>Owner</th></tr>
      <tr><td>SECOND BOAT</td><td>DOC-002</td><td>Owner B</td></tr>
    </table>
    </body></html>
    """
    vessels = _parse_uscg_html(html)
    names = [v["vessel_name"] for v in vessels]
    assert "FIRST BOAT" in names
    # Second table should NOT be processed due to break
    assert "SECOND BOAT" not in names


def test_parse_uscg_html_exception_returns_empty_list():
    """Lines 326-327: exception inside the USCG parser is caught and returns []."""
    from unittest.mock import MagicMock, patch

    bad_soup = MagicMock()
    bad_soup.find_all.side_effect = RuntimeError("simulated uscg failure")

    with patch("bs4.BeautifulSoup", return_value=bad_soup):
        vessels = _parse_uscg_html("<html><body></body></html>")

    assert vessels == []


# ---------------------------------------------------------------------------
# _parse_marinetraffic_html — outer exception path (lines 177-178)
# ---------------------------------------------------------------------------


def test_parse_marinetraffic_html_outer_exception_returns_empty():
    """Lines 177-178: outer except in _parse_marinetraffic_html → returns []."""
    from modules.crawlers.transport.marine_vessel import _parse_marinetraffic_html

    with patch("bs4.BeautifulSoup", side_effect=Exception("mt boom")):
        vessels = _parse_marinetraffic_html("<html></html>")
    assert vessels == []
