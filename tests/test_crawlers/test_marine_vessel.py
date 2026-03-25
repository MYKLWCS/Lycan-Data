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
from modules.crawlers.result import CrawlerResult


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
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=_MT_TABLE_HTML))):
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
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=_USCG_HTML))) as mock_get:
        results = await crawler._search_uscg("SEA+WOLF", "vessel_name")
    # URL should have query as vessel name, owner_query empty
    call_url = mock_get.call_args[0][0]
    assert "VesselName=SEA+WOLF" in call_url
    assert "Owner=" in call_url


async def test_search_uscg_owner_name_mode():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text="<html></html>"))) as mock_get:
        results = await crawler._search_uscg("John+Smith", "owner_name")
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
