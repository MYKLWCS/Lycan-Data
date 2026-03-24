"""
Tests for Vehicle Records scrapers — Tasks 35.
  - VehicleNhtsaCrawler    (vehicle_nhtsa)
  - VehiclePlateCrawler    (vehicle_plate)
  - VehicleOwnershipCrawler (vehicle_ownership)

15 tests total — HTTP/Playwright calls are mocked.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Trigger @register decorators
import modules.crawlers.vehicle_nhtsa     # noqa: F401
import modules.crawlers.vehicle_plate     # noqa: F401
import modules.crawlers.vehicle_ownership  # noqa: F401

from modules.crawlers.vehicle_nhtsa import (
    VehicleNhtsaCrawler,
    _validate_vin,
    _parse_decode_results,
    _parse_recalls,
)
from modules.crawlers.vehicle_plate import (
    VehiclePlateCrawler,
    _parse_identifier as _plate_parse_id,
    _parse_faxvin_json,
    _parse_licenseplatedata_html,
)
from modules.crawlers.vehicle_ownership import (
    VehicleOwnershipCrawler,
    _parse_identifier as _owner_parse_id,
    _parse_vehicle_cards_html,
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


# Sample NHTSA VIN decode response
SAMPLE_NHTSA_DECODE = {
    "Count": 136,
    "Results": [
        {"Variable": "Make",                 "Value": "HONDA",            "ValueId": ""},
        {"Variable": "Model",                "Value": "Civic",            "ValueId": ""},
        {"Variable": "Model Year",           "Value": "2022",             "ValueId": ""},
        {"Variable": "Body Class",           "Value": "Sedan/Saloon",     "ValueId": ""},
        {"Variable": "Engine Configuration", "Value": "In-Line",          "ValueId": ""},
        {"Variable": "Fuel Type - Primary",  "Value": "Gasoline",         "ValueId": ""},
        {"Variable": "Manufacturer Name",    "Value": "HONDA OF AMERICA", "ValueId": ""},
        {"Variable": "Plant Country",        "Value": "UNITED STATES",    "ValueId": ""},
        {"Variable": "Plant State",          "Value": "OHIO",             "ValueId": ""},
        {"Variable": "Vehicle Type",         "Value": "PASSENGER CAR",   "ValueId": ""},
        {"Variable": "Drive Type",           "Value": "FWD/Front Wheel Drive", "ValueId": ""},
        {"Variable": "Transmission Style",   "Value": "Automatic",        "ValueId": ""},
        # Junk entry — should be ignored
        {"Variable": "ErrorCode",            "Value": "0",                "ValueId": ""},
    ],
}

SAMPLE_NHTSA_RECALLS = {
    "Count": 1,
    "results": [
        {
            "Component":           "AIR BAGS",
            "Summary":             "Takata airbag inflator may rupture.",
            "Consequence":         "Metal fragments could cause injury.",
            "Remedy":              "Dealers will replace the airbag inflator.",
            "NHTSACampaignNumber": "21V123456",
        }
    ],
}

SAMPLE_FAXVIN_JSON = {
    "vehicle": {
        "year":       "2019",
        "make":       "Toyota",
        "model":      "Camry",
        "vin":        "4T1B11HK3KU123456",
        "color":      "Silver",
        "body_style": "Sedan",
    }
}

SAMPLE_PLATE_HTML = """
<html><body>
  <div class="result-label">Year</div>
  <div class="result-value">2020</div>
  <div class="result-label">Make</div>
  <div class="result-value">Ford</div>
  <div class="result-label">Model</div>
  <div class="result-value">F-150</div>
  <div class="result-label">VIN</div>
  <div class="result-value">1FTEW1EP0LFA12345</div>
</body></html>
"""

SAMPLE_OWNERSHIP_HTML = """
<html><body>
  <div class="vehicle-card">
    Year: 2018 Make: Chevrolet Model: Silverado
    VIN: 1GCVKNEC3JZ123456
    Plate: TXB1234 State: TX Color: Black
  </div>
  <div class="vehicle-card">
    Year: 2015 Make: Ford Model: Explorer
    Plate: TXC9876 State: TX
  </div>
</body></html>
"""


# ===========================================================================
# 1. Registry tests
# ===========================================================================

def test_vehicle_nhtsa_registered():
    assert is_registered("vehicle_nhtsa")


def test_vehicle_plate_registered():
    assert is_registered("vehicle_plate")


def test_vehicle_ownership_registered():
    assert is_registered("vehicle_ownership")


# ===========================================================================
# 2. VIN validation
# ===========================================================================

def test_validate_vin_valid():
    assert _validate_vin("1HGBH41JXMN109186") is True


def test_validate_vin_too_short():
    assert _validate_vin("1HGBH41JXMN10918") is False


def test_validate_vin_invalid_chars():
    # Contains 'O' (forbidden)
    assert _validate_vin("1HGBH41JXMO109186") is False


def test_validate_vin_lowercase_accepted():
    # VIN function should uppercase before checking
    assert _validate_vin("1hgbh41jxmn109186") is True


# ===========================================================================
# 3. _parse_decode_results
# ===========================================================================

def test_parse_decode_results_extracts_fields():
    data = _parse_decode_results(SAMPLE_NHTSA_DECODE["Results"])
    assert data["make"] == "HONDA"
    assert data["model"] == "Civic"
    assert data["year"] == "2022"
    assert data["body_class"] == "Sedan/Saloon"
    assert data["fuel_type"] == "Gasoline"
    # ErrorCode should NOT appear
    assert "error_code" not in data


def test_parse_decode_results_empty():
    data = _parse_decode_results([])
    assert data == {}


def test_parse_recalls_extracts_fields():
    recalls = _parse_recalls(SAMPLE_NHTSA_RECALLS["results"])
    assert len(recalls) == 1
    assert recalls[0]["component"] == "AIR BAGS"
    assert "rupture" in recalls[0]["summary"].lower()
    assert recalls[0]["campaign_id"] == "21V123456"


# ===========================================================================
# 4. VehicleNhtsaCrawler — scrape()
# ===========================================================================

@pytest.mark.asyncio
async def test_nhtsa_found():
    """Valid VIN returns make/model/year + recalls."""
    crawler = VehicleNhtsaCrawler()
    mock_decode  = _mock_resp(200, json_data=SAMPLE_NHTSA_DECODE)
    mock_recalls = _mock_resp(200, json_data=SAMPLE_NHTSA_RECALLS)

    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_decode, mock_recalls])):
        result = await crawler.scrape("1HGBH41JXMN109186")

    assert result.found is True
    assert result.data["make"] == "HONDA"
    assert result.data["vin"] == "1HGBH41JXMN109186"
    assert isinstance(result.data["recalls"], list)


@pytest.mark.asyncio
async def test_nhtsa_invalid_vin():
    """Bad VIN format returns error without making HTTP calls."""
    crawler = VehicleNhtsaCrawler()
    with patch.object(crawler, "get", new=AsyncMock()) as mock_get:
        result = await crawler.scrape("BADVIN123")
    assert result.found is False
    assert result.data.get("error") == "invalid_vin"
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_nhtsa_http_error():
    """Network failure returns error result."""
    crawler = VehicleNhtsaCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("1HGBH41JXMN109186")
    assert result.found is False
    assert result.data.get("error") == "http_error"


# ===========================================================================
# 5. _parse_identifier (plate)
# ===========================================================================

def test_plate_parse_identifier_with_state():
    plate, state = _plate_parse_id("ABC1234|TX")
    assert plate == "ABC1234"
    assert state == "TX"


def test_plate_parse_identifier_no_state():
    plate, state = _plate_parse_id("XYZ9999")
    assert plate == "XYZ9999"
    assert state == ""


# ===========================================================================
# 6. _parse_faxvin_json
# ===========================================================================

def test_parse_faxvin_json_full():
    result = _parse_faxvin_json(SAMPLE_FAXVIN_JSON)
    assert result["make"] == "Toyota"
    assert result["model"] == "Camry"
    assert result["year"] == "2019"
    assert result["vin"] == "4T1B11HK3KU123456"


# ===========================================================================
# 7. VehiclePlateCrawler — scrape()
# ===========================================================================

@pytest.mark.asyncio
async def test_plate_found_via_faxvin():
    """faxvin JSON response → found result with make/model."""
    crawler = VehiclePlateCrawler()
    mock_faxvin = _mock_resp(200, json_data=SAMPLE_FAXVIN_JSON)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_faxvin)):
        result = await crawler.scrape("ABC1234|TX")

    assert result.found is True
    assert result.data["plate"] == "ABC1234"
    assert result.data["make"] == "Toyota"


@pytest.mark.asyncio
async def test_plate_not_found():
    """All sources return 404 → not found."""
    crawler = VehiclePlateCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        result = await crawler.scrape("ZZZ9999|TX")
    assert result.found is False


# ===========================================================================
# 8. _parse_vehicle_cards_html (ownership)
# ===========================================================================

def test_parse_vehicle_cards_html_finds_vehicles():
    vehicles = _parse_vehicle_cards_html(SAMPLE_OWNERSHIP_HTML)
    assert len(vehicles) >= 1
    # Should find at least the Chevrolet with VIN
    vins = [v.get("vin") for v in vehicles]
    assert "1GCVKNEC3JZ123456" in vins


# ===========================================================================
# 9. VehicleOwnershipCrawler — scrape() with mocked Playwright
# ===========================================================================

@pytest.mark.asyncio
async def test_ownership_found():
    """Mocked Playwright returns HTML with vehicle cards."""
    crawler = VehicleOwnershipCrawler()

    async def _mock_scrape_vh(first, last):
        return _parse_vehicle_cards_html(SAMPLE_OWNERSHIP_HTML)

    async def _mock_scrape_bv(first, last):
        return []

    with patch.object(crawler, "_scrape_vehiclehistory", side_effect=_mock_scrape_vh):
        with patch.object(crawler, "_scrape_beenverified", side_effect=_mock_scrape_bv):
            result = await crawler.scrape("John Smith|Austin,TX")

    assert result.found is True
    assert len(result.data["vehicles"]) >= 1
    assert result.data["owner_name"] == "John Smith"


@pytest.mark.asyncio
async def test_ownership_not_found():
    """No vehicles found → found=False."""
    crawler = VehicleOwnershipCrawler()

    async def _mock_empty(first, last):
        return []

    with patch.object(crawler, "_scrape_vehiclehistory", side_effect=_mock_empty):
        with patch.object(crawler, "_scrape_beenverified", side_effect=_mock_empty):
            result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.data["vehicles"] == []


@pytest.mark.asyncio
async def test_ownership_parse_identifier():
    """_parse_identifier correctly splits full identifier."""
    first, last, city, state = _owner_parse_id("John Smith|Houston,TX")
    assert first == "John"
    assert last == "Smith"
    assert city == "Houston"
    assert state == "TX"
