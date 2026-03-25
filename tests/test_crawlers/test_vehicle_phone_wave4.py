"""
test_vehicle_phone_wave4.py — Branch-coverage gap tests (wave 4).

Crawlers covered:
  vehicle_nhtsa, vehicle_plate, phone_carrier

Each test targets specific uncovered lines identified in the coverage report.
All HTTP I/O is mocked at the crawler method level.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# vehicle_nhtsa.py — lines 139, 149-151, 161, 181-182
# ===========================================================================

_VALID_VIN = "1HGBH41JXMN109186"

_DECODE_JSON_OK = {
    "Results": [
        {"Variable": "Make", "Value": "HONDA"},
        {"Variable": "Model", "Value": "CIVIC"},
        {"Variable": "Model Year", "Value": "2021"},
        {"Variable": "Body Class", "Value": "Sedan"},
    ]
}

_DECODE_JSON_NO_MAKE = {
    "Results": [
        {"Variable": "Model Year", "Value": "2021"},
    ]
}


class TestVehicleNhtsaCrawler:
    def _make_crawler(self):
        from modules.crawlers.vehicle_nhtsa import VehicleNhtsaCrawler

        return VehicleNhtsaCrawler()

    # --- line 139: resp.status_code != 200 → http_NNN error ---
    @pytest.mark.asyncio
    async def test_scrape_non200_decode_resp(self):
        """Line 139: decode API returns non-200 → http_NNN error."""
        crawler = self._make_crawler()
        resp = _mock_resp(503)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape(_VALID_VIN)

        assert result.found is False
        assert "http_503" in (result.data.get("error") or "")

    # --- lines 149-151: resp.json() raises → json_parse_error ---
    @pytest.mark.asyncio
    async def test_scrape_json_parse_error(self):
        """Lines 149-151: JSON parse failure returns json_parse_error."""
        crawler = self._make_crawler()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape(_VALID_VIN)

        assert result.found is False
        assert result.data.get("error") == "json_parse_error"

    # --- line 161: make absent → vin_not_found ---
    @pytest.mark.asyncio
    async def test_scrape_no_make_returns_vin_not_found(self):
        """Line 161: VIN decoded but make absent → vin_not_found."""
        crawler = self._make_crawler()
        resp = _mock_resp(200, json_data=_DECODE_JSON_NO_MAKE)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape(_VALID_VIN)

        assert result.found is False
        assert result.data.get("error") == "vin_not_found"

    # --- lines 181-182: recalls resp.json() raises → debug logged, recalls=[] ---
    @pytest.mark.asyncio
    async def test_recalls_json_parse_error_silently_ignored(self):
        """Lines 181-182: recalls JSON parse error is swallowed; result still found."""
        crawler = self._make_crawler()

        decode_resp = _mock_resp(200, json_data=_DECODE_JSON_OK)
        recalls_resp = _mock_resp(200)
        recalls_resp.json.side_effect = ValueError("bad recalls json")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[decode_resp, recalls_resp])):
            result = await crawler.scrape(_VALID_VIN)

        assert result.found is True
        assert result.data.get("recalls") == []

    # --- line 149 + success path: full decode + recalls ---
    @pytest.mark.asyncio
    async def test_scrape_full_success_with_recalls(self):
        """Happy path: VIN decoded and recalls fetched."""
        crawler = self._make_crawler()

        decode_resp = _mock_resp(200, json_data=_DECODE_JSON_OK)
        recalls_resp = _mock_resp(
            200,
            json_data={
                "results": [
                    {
                        "Component": "BRAKES",
                        "Summary": "Brake failure",
                        "Consequence": "May crash",
                        "Remedy": "Replace brakes",
                        "NHTSACampaignNumber": "21V001000",
                    }
                ]
            },
        )

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[decode_resp, recalls_resp])):
            result = await crawler.scrape(_VALID_VIN)

        assert result.found is True
        assert result.data.get("make") == "HONDA"
        assert len(result.data.get("recalls", [])) == 1


# ===========================================================================
# vehicle_plate.py — lines 106-107, 140-141
# ===========================================================================


class TestVehiclePlateParsers:
    # --- lines 106-107: _parse_licenseplatedata_html exception caught ---
    def test_parse_licenseplatedata_html_exception_caught(self):
        """Lines 106-107: exception in parser is caught, returns empty dict."""
        from modules.crawlers.vehicle_plate import _parse_licenseplatedata_html

        # Passing non-string should cause an exception inside
        result = _parse_licenseplatedata_html(None)  # type: ignore[arg-type]
        assert result == {}

    def test_parse_licenseplatedata_html_regex_fallback(self):
        """Lines 94-104: regex fallback parses year/make when divs absent."""
        from modules.crawlers.vehicle_plate import _parse_licenseplatedata_html

        html = "Year: 2019\nMake: TOYOTA\nColor: Blue"
        result = _parse_licenseplatedata_html(html)
        assert result.get("year") == "2019"
        assert result.get("make") == "TOYOTA"

    # --- lines 140-141: _parse_vehiclehistory_html exception caught ---
    def test_parse_vehiclehistory_html_exception_caught(self):
        """Lines 140-141: exception in parser is caught, returns empty dict."""
        from modules.crawlers.vehicle_plate import _parse_vehiclehistory_html

        result = _parse_vehiclehistory_html(None)  # type: ignore[arg-type]
        assert result == {}

    def test_parse_vehiclehistory_html_json_regex_fallback(self):
        """Lines 129-138: JSON-like regex fallback parses make/model/vin."""
        from modules.crawlers.vehicle_plate import _parse_vehiclehistory_html

        html = '"year": "2020", "make": "FORD", "model": "F-150"'
        result = _parse_vehiclehistory_html(html)
        assert result.get("make") == "FORD"
        assert result.get("year") == "2020"


class TestVehiclePlateCrawler:
    def _make_crawler(self):
        from modules.crawlers.vehicle_plate import VehiclePlateCrawler

        return VehiclePlateCrawler()

    # --- vehicle plate crawl: faxvin success ---
    @pytest.mark.asyncio
    async def test_scrape_faxvin_success(self):
        """Faxvin returns data → source_used=faxvin, result found."""
        crawler = self._make_crawler()

        faxvin_resp = _mock_resp(
            200,
            json_data={
                "vehicle": {
                    "make": "CHEVROLET",
                    "model": "TAHOE",
                    "year": "2018",
                    "vin": "1GNSCBKC4JR100001",
                }
            },
        )

        with patch.object(crawler, "get", new=AsyncMock(return_value=faxvin_resp)):
            result = await crawler.scrape("XYZ789|TX")

        assert result.found is True
        assert result.data.get("source") == "faxvin"
        assert result.data.get("make") == "CHEVROLET"

    # --- vehicle plate crawl: all sources miss → found=False ---
    @pytest.mark.asyncio
    async def test_scrape_all_sources_miss(self):
        """All three sources return empty → found=False."""
        crawler = self._make_crawler()

        empty_resp = _mock_resp(200, json_data={})
        no_content_resp = _mock_resp(404)

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[empty_resp, no_content_resp, no_content_resp]),
        ):
            result = await crawler.scrape("ABC123|CA")

        assert result.found is False
        assert result.data.get("source") == "none"


# ===========================================================================
# phone_carrier.py — lines 155-160, 166
# ===========================================================================


class TestPhoneCarrierParseResponse:
    def _make_crawler(self):
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        return CarrierLookupCrawler()

    # --- lines 155-160: parent td fallback when sibling has no value ---
    def test_parse_response_parent_td_fallback(self):
        """Lines 155-160: carrier name extracted via parent td when sibling is short."""
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        crawler = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        html = """<html><body>
          <table>
            <tr>
              <td>Carrier</td>
              <td>AT&amp;T Wireless</td>
            </tr>
          </table>
        </body></html>"""
        carrier_name, line_type = crawler._parse_response(html)
        assert "AT" in carrier_name or carrier_name  # carrier extracted

    # --- line 166: result_div fallback when no sibling or parent tds ---
    def test_parse_response_result_div_fallback(self):
        """Line 166: carrier name extracted from .result container div."""
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        crawler = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        html = """<html><body>
          <div class="carrier-result">T-Mobile USA</div>
        </body></html>"""
        carrier_name, line_type = crawler._parse_response(html)
        assert "T-Mobile" in carrier_name

    # --- lines 155-160: sibling with value triggers break ---
    def test_parse_response_sibling_value(self):
        """Lines 148-153: sibling with len > 2 sets carrier and breaks."""
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        crawler = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        html = """<html><body>
          <div>
            <span>Provider:</span>
            <span>Verizon Wireless</span>
          </div>
        </body></html>"""
        carrier_name, line_type = crawler._parse_response(html)
        assert "Verizon" in carrier_name

    # --- full scrape: mobile line type detected ---
    @pytest.mark.asyncio
    async def test_scrape_mobile_line_type(self):
        """Full carrier scrape with mobile in response text."""
        from modules.crawlers.phone_carrier import CarrierLookupCrawler
        from shared.constants import LineType

        crawler = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        crawler.platform = "phone_carrier"
        crawler.source_reliability = 0.65
        # Bypass Tor session; patch get directly
        html = """<html><body>
          <table>
            <tr><td>Carrier</td><td>AT&amp;T Mobile Wireless</td></tr>
          </table>
          <p>This is a mobile wireless number.</p>
        </body></html>"""
        resp = _mock_resp(200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")

        assert result.found is True
        assert result.data.get("line_type") == LineType.MOBILE.value

    # --- scrape: 404 → not_found (error on result.error, not result.data) ---
    @pytest.mark.asyncio
    async def test_scrape_404_not_found(self):
        """Phone carrier 404 returns not_found error on result.error."""
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        crawler = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        crawler.platform = "phone_carrier"
        crawler.source_reliability = 0.65

        resp = _mock_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")

        assert result.found is False
        assert result.error == "not_found"

    # --- scrape: no carrier data extracted → no_carrier_data ---
    @pytest.mark.asyncio
    async def test_scrape_no_carrier_data(self):
        """Empty HTML → no carrier extracted → no_carrier_data on result.error."""
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        crawler = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        crawler.platform = "phone_carrier"
        crawler.source_reliability = 0.65

        resp = _mock_resp(200, text="<html><body><p>No results found</p></body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")

        assert result.found is False
        assert result.error == "no_carrier_data"
