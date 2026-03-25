"""
test_redfin_deep.py — 100% line coverage for modules/crawlers/property/redfin_deep.py

asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
All HTTP I/O is mocked via patch.object(crawler, 'get', new_callable=AsyncMock).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = "", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (json.dumps(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _xssi(data: dict) -> str:
    return "{} && " + json.dumps(data)


# ---------------------------------------------------------------------------
# _strip_xssi
# ---------------------------------------------------------------------------


class TestStripXssi:
    def test_removes_prefix(self):
        from modules.crawlers.property.redfin_deep import _strip_xssi

        raw = '{} && {"payload": {}}'
        result = _strip_xssi(raw)
        assert result.startswith('{"payload"')

    def test_no_prefix_unchanged(self):
        from modules.crawlers.property.redfin_deep import _strip_xssi

        raw = '{"payload": {}}'
        assert _strip_xssi(raw) == raw

    def test_empty_string(self):
        from modules.crawlers.property.redfin_deep import _strip_xssi

        assert _strip_xssi("") == ""


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------


class TestParseJson:
    def test_valid_json(self):
        from modules.crawlers.property.redfin_deep import _parse_json

        result = _parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_xssi_prefixed_json(self):
        from modules.crawlers.property.redfin_deep import _parse_json

        raw = '{} && {"key": "value"}'
        result = _parse_json(raw)
        assert result == {"key": "value"}

    def test_invalid_returns_empty(self):
        from modules.crawlers.property.redfin_deep import _parse_json

        assert _parse_json("not json") == {}

    def test_empty_string_returns_empty(self):
        from modules.crawlers.property.redfin_deep import _parse_json

        assert _parse_json("") == {}


# ---------------------------------------------------------------------------
# _money
# ---------------------------------------------------------------------------


class TestMoneyHelper:
    def test_none_returns_none(self):
        from modules.crawlers.property.redfin_deep import _money

        assert _money(None) is None

    def test_int_passthrough(self):
        from modules.crawlers.property.redfin_deep import _money

        assert _money(400000) == 400000

    def test_float_truncated(self):
        from modules.crawlers.property.redfin_deep import _money

        assert _money(399999.5) == 399999

    def test_string_with_formatting(self):
        from modules.crawlers.property.redfin_deep import _money

        assert _money("$1,200,000") == 1200000

    def test_bad_string_returns_none(self):
        from modules.crawlers.property.redfin_deep import _money

        assert _money("N/A") is None


# ---------------------------------------------------------------------------
# _parse_autocomplete
# ---------------------------------------------------------------------------


class TestParseAutocomplete:
    def test_empty_payload(self):
        from modules.crawlers.property.redfin_deep import _parse_autocomplete

        assert _parse_autocomplete({}) == []
        assert _parse_autocomplete({"payload": {}}) == []

    def test_sections_with_rows(self):
        from modules.crawlers.property.redfin_deep import _parse_autocomplete

        data = {
            "payload": {
                "sections": [
                    {
                        "rows": [
                            {
                                "name": "123 Main St",
                                "url": "/home/123",
                                "id": "abc",
                                "type": "address",
                            }
                        ]
                    }
                ]
            }
        }
        stubs = _parse_autocomplete(data)
        assert len(stubs) == 1
        assert stubs[0]["display"] == "123 Main St"
        assert stubs[0]["url"] == "/home/123"

    def test_multiple_sections(self):
        from modules.crawlers.property.redfin_deep import _parse_autocomplete

        data = {
            "payload": {
                "sections": [
                    {"rows": [{"name": "A"}, {"name": "B"}]},
                    {"rows": [{"name": "C"}]},
                ]
            }
        }
        stubs = _parse_autocomplete(data)
        assert len(stubs) == 3

    def test_section_no_rows_key(self):
        from modules.crawlers.property.redfin_deep import _parse_autocomplete

        data = {"payload": {"sections": [{}]}}
        assert _parse_autocomplete(data) == []


# ---------------------------------------------------------------------------
# _extract_property_id
# ---------------------------------------------------------------------------


class TestExtractPropertyId:
    def test_numeric_id_in_url_path(self):
        from modules.crawlers.property.redfin_deep import _extract_property_id

        assert _extract_property_id("/home/12345") == "12345"

    def test_query_param_fallback(self):
        from modules.crawlers.property.redfin_deep import _extract_property_id

        assert _extract_property_id("/home?propertyId=98765") == "98765"

    def test_no_id_returns_none(self):
        from modules.crawlers.property.redfin_deep import _extract_property_id

        assert _extract_property_id("/home/slug-only") is None

    def test_id_at_end_of_url(self):
        from modules.crawlers.property.redfin_deep import _extract_property_id

        assert _extract_property_id("/TX/Dallas/home/11111") == "11111"


# ---------------------------------------------------------------------------
# _parse_gis
# ---------------------------------------------------------------------------


class TestParseGis:
    def test_empty_payload(self):
        from modules.crawlers.property.redfin_deep import _parse_gis

        assert _parse_gis({}) == []
        assert _parse_gis({"payload": {}}) == []

    def test_basic_home(self):
        from modules.crawlers.property.redfin_deep import _parse_gis

        data = {
            "payload": {
                "homes": [
                    {
                        "address": {
                            "streetAddress": "123 Main St",
                            "city": "Dallas",
                            "state": "TX",
                            "zip": "75001",
                        },
                        "latLong": {"latitude": 32.78, "longitude": -96.79},
                        "homeType": "Single Family",
                        "price": 450000,
                        "beds": 3,
                        "baths": 2.0,
                        "sqFt": 1500,
                        "yearBuilt": 2005,
                        "lastSoldPrice": 400000,
                        "lastSoldDate": "2020-01-15",
                        "url": "/TX/Dallas/home/123",
                        "propertyId": "999",
                    }
                ]
            }
        }
        props = _parse_gis(data)
        assert len(props) == 1
        assert props[0]["city"] == "Dallas"
        assert props[0]["current_market_value_usd"] == 450000
        assert props[0]["property_id"] == "999"

    def test_url_used_for_property_id_when_not_set(self):
        from modules.crawlers.property.redfin_deep import _parse_gis

        data = {
            "payload": {
                "homes": [
                    {
                        "address": {"streetAddress": "1 A", "city": "X", "state": "TX", "zip": "00001"},
                        "latLong": {},
                        "url": "/home/55555",
                    }
                ]
            }
        }
        props = _parse_gis(data)
        assert props[0]["property_id"] == "55555"

    def test_truncates_at_10(self):
        from modules.crawlers.property.redfin_deep import _parse_gis

        homes = [
            {
                "address": {"streetAddress": f"{i} St", "city": "X", "state": "TX", "zip": "00001"},
                "latLong": {},
                "url": f"/home/{i}",
            }
            for i in range(15)
        ]
        props = _parse_gis({"payload": {"homes": homes}})
        assert len(props) == 10


# ---------------------------------------------------------------------------
# _parse_detail
# ---------------------------------------------------------------------------


class TestParseDetail:
    def test_empty_data(self):
        from modules.crawlers.property.redfin_deep import _parse_detail

        result = _parse_detail({})
        assert result.get("owner_name") is None

    def test_full_payload(self):
        from modules.crawlers.property.redfin_deep import _parse_detail

        data = {
            "payload": {
                "publicRecordsInfo": {
                    "apn": "123-456",
                    "countyFips": "48113",
                    "zoning": "R1",
                    "floodZoneDescription": "Zone X",
                    "lotSqFt": 8500,
                    "numStories": 2,
                    "numParkingGarage": 2,
                    "hasPool": True,
                    "assessedValue": "320000",
                    "taxAmount": "4800",
                    "ownerName": "SMITH JOHN",
                    "ownerAddress": "PO Box 1",
                    "ownerOccupied": True,
                    "homesteadExemption": True,
                    "mortgageHistory": [
                        {
                            "lenderName": "Chase",
                            "loanType": "Conventional",
                            "loanAmount": "280000",
                            "originationDate": "2020-03-01",
                            "isActive": True,
                        }
                    ],
                },
                "schoolsInfo": {
                    "servingThisHome": [{"districtName": "Dallas ISD"}]
                },
                "walkScore": {"walkScore": 72, "transitScore": 55, "bikeScore": 40},
            }
        }
        result = _parse_detail(data)
        assert result["parcel_number"] == "123-456"
        assert result["owner_name"] == "SMITH JOHN"
        assert result["walk_score"] == 72
        assert len(result["mortgages"]) == 1
        assert result["mortgages"][0]["lender_name"] == "Chase"
        assert result["school_district"] == "Dallas ISD"

    def test_no_schools_sets_none(self):
        from modules.crawlers.property.redfin_deep import _parse_detail

        data = {"payload": {"publicRecordsInfo": {}, "schoolsInfo": {"servingThisHome": []}}}
        result = _parse_detail(data)
        assert result["school_district"] is None

    def test_exception_in_parse_returns_partial(self):
        from modules.crawlers.property.redfin_deep import _parse_detail

        # Force an exception by passing something that breaks attribute access
        result = _parse_detail({"payload": {"publicRecordsInfo": "not-a-dict"}})
        # Returns empty or partial — must not raise
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _parse_price_history
# ---------------------------------------------------------------------------


class TestParsePriceHistory:
    def test_empty_data(self):
        from modules.crawlers.property.redfin_deep import _parse_price_history

        assert _parse_price_history({}) == []

    def test_sold_event_price_set(self):
        from modules.crawlers.property.redfin_deep import _parse_price_history

        data = {
            "payload": {
                "rows": [
                    {
                        "eventName": "Sold",
                        "price": 380000,
                        "soldDate": "2022-05-01",
                        "documentNumber": "DOC123",
                        "sellerName": "JONES MARY",
                        "buyerName": "SMITH JOHN",
                        "loanAmount": 300000,
                    }
                ]
            }
        }
        result = _parse_price_history(data)
        assert len(result) == 1
        assert result[0]["acquisition_price_usd"] == 380000
        assert result[0]["grantor"] == "JONES MARY"

    def test_non_sold_event_price_none(self):
        from modules.crawlers.property.redfin_deep import _parse_price_history

        data = {
            "payload": {
                "rows": [
                    {"eventName": "Listed", "price": 400000, "date": "2022-01-01"}
                ]
            }
        }
        result = _parse_price_history(data)
        assert result[0]["acquisition_price_usd"] is None

    def test_date_fallback_to_date_key(self):
        from modules.crawlers.property.redfin_deep import _parse_price_history

        data = {
            "payload": {
                "rows": [{"eventName": "Sold", "price": 300000, "date": "2019-06-01"}]
            }
        }
        result = _parse_price_history(data)
        assert result[0]["acquisition_date"] == "2019-06-01"

    def test_source_fallback_when_no_eventname(self):
        from modules.crawlers.property.redfin_deep import _parse_price_history

        data = {
            "payload": {
                "rows": [{"source": "MLS", "price": 200000}]
            }
        }
        result = _parse_price_history(data)
        assert result[0]["acquisition_type"] == "MLS"

    def test_exception_returns_empty(self):
        from modules.crawlers.property.redfin_deep import _parse_price_history

        result = _parse_price_history({"payload": {"rows": "not-a-list"}})
        assert result == []


# ---------------------------------------------------------------------------
# _parse_tax_history
# ---------------------------------------------------------------------------


class TestParseTaxHistory:
    def test_empty_data(self):
        from modules.crawlers.property.redfin_deep import _parse_tax_history

        assert _parse_tax_history({}) == []

    def test_full_tax_rows(self):
        from modules.crawlers.property.redfin_deep import _parse_tax_history

        data = {
            "payload": {
                "publicRecordsInfo": {
                    "taxHistories": [
                        {
                            "taxYear": 2021,
                            "assessedValue": "320000",
                            "marketValue": "400000",
                            "taxAmount": "4800",
                        }
                    ]
                }
            }
        }
        result = _parse_tax_history(data)
        assert len(result) == 1
        assert result[0]["valuation_year"] == 2021
        assert result[0]["assessed_value_usd"] == 320000
        assert result[0]["tax_amount_usd"] == 4800

    def test_no_tax_histories_returns_empty(self):
        from modules.crawlers.property.redfin_deep import _parse_tax_history

        data = {"payload": {"publicRecordsInfo": {}}}
        assert _parse_tax_history(data) == []

    def test_exception_in_tax_history_returns_empty(self):
        """Lines 258-259: exception during parsing returns empty list."""
        from modules.crawlers.property.redfin_deep import _parse_tax_history

        # Passing non-iterable taxHistories to force an exception
        data = {"payload": {"publicRecordsInfo": {"taxHistories": "not-a-list"}}}
        result = _parse_tax_history(data)
        assert result == []


# ---------------------------------------------------------------------------
# RedfinDeepCrawler.scrape
# ---------------------------------------------------------------------------


class TestRedfinDeepCrawlerScrape:
    def _make_crawler(self):
        from modules.crawlers.property.redfin_deep import RedfinDeepCrawler

        return RedfinDeepCrawler()

    def _gis_data(self):
        return {
            "payload": {
                "homes": [
                    {
                        "address": {
                            "streetAddress": "123 Main St",
                            "city": "Dallas",
                            "state": "TX",
                            "zip": "75001",
                        },
                        "latLong": {"latitude": 32.78, "longitude": -96.79},
                        "propertyId": "123",
                        "url": "/TX/Dallas/home/123",
                    }
                ]
            }
        }

    async def test_gis_none_response_returns_not_found(self):
        crawler = self._make_crawler()

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text="{}")
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St Dallas TX")
        assert result.found is False

    async def test_gis_non_200_206_returns_not_found(self):
        crawler = self._make_crawler()

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text="{}")
            return _mock_resp(status=503, text="Service Unavailable")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St Dallas TX")
        assert result.found is False

    async def test_gis_206_accepted(self):
        crawler = self._make_crawler()
        gis_text = json.dumps(self._gis_data())

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text="{}")
            if "gis" in url:
                return _mock_resp(status=206, text=gis_text)
            return _mock_resp(status=200, text="{}")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St Dallas TX")
        assert result.found is True

    async def test_empty_gis_properties_returns_not_found(self):
        crawler = self._make_crawler()
        empty_gis = json.dumps({"payload": {"homes": []}})

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text="{}")
            return _mock_resp(status=200, text=empty_gis)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("unknown address")
        assert result.found is False

    async def test_full_scrape_with_detail_and_history(self):
        crawler = self._make_crawler()
        gis_text = json.dumps(self._gis_data())
        detail_data = {
            "payload": {
                "publicRecordsInfo": {
                    "apn": "123-456",
                    "ownerName": "SMITH JOHN",
                    "taxHistories": [{"taxYear": 2021, "assessedValue": "300000", "taxAmount": "4500"}],
                },
                "schoolsInfo": {"servingThisHome": []},
                "walkScore": {"walkScore": 70},
            }
        }
        hist_data = {
            "payload": {
                "rows": [{"eventName": "Sold", "price": 380000, "soldDate": "2022-05-01"}]
            }
        }

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text="{}")
            if "gis" in url:
                return _mock_resp(status=200, text=gis_text)
            if "belowTheFold" in url:
                return _mock_resp(status=200, text=json.dumps(detail_data))
            if "ml_history" in url:
                return _mock_resp(status=200, text=json.dumps(hist_data))
            return _mock_resp(status=200, text="{}")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St Dallas TX")

        assert result.found is True
        props = result.data["properties"]
        assert len(props) >= 1
        assert props[0].get("owner_name") == "SMITH JOHN"
        assert len(props[0].get("ownership_history", [])) == 1

    async def test_no_property_id_falls_back_to_autocomplete(self):
        crawler = self._make_crawler()
        # GIS home has no propertyId and no URL with id
        gis_data = {
            "payload": {
                "homes": [
                    {
                        "address": {"streetAddress": "1 A St", "city": "X", "state": "TX", "zip": "00001"},
                        "latLong": {},
                        "url": "/home/no-id-here",
                    }
                ]
            }
        }
        autocomplete_data = {
            "payload": {
                "sections": [
                    {"rows": [{"name": "1 A St", "url": "/home/77777", "id": "x", "type": "address"}]}
                ]
            }
        }

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(status=200, text=json.dumps(autocomplete_data))
            if "gis" in url:
                return _mock_resp(status=200, text=json.dumps(gis_data))
            return _mock_resp(status=200, text="{}")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("1 A St TX")
        assert result.found is True

    async def test_autocomplete_none_response_continues(self):
        crawler = self._make_crawler()
        gis_text = json.dumps(self._gis_data())

        async def fake_get(url, **kwargs):
            if "autocomplete" in url:
                return None  # autocomplete fails gracefully
            if "gis" in url:
                return _mock_resp(status=200, text=gis_text)
            return _mock_resp(status=200, text="{}")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St Dallas TX")
        assert result.found is True


# ---------------------------------------------------------------------------
# RedfinDeepCrawler._fetch_detail and _fetch_price_history
# ---------------------------------------------------------------------------


class TestRedfinDeepFetchHelpers:
    def _make_crawler(self):
        from modules.crawlers.property.redfin_deep import RedfinDeepCrawler

        return RedfinDeepCrawler()

    async def test_fetch_detail_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._fetch_detail("123")
        assert result == {}

    async def test_fetch_detail_non_200(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="not found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_detail("123")
        assert result == {}

    async def test_fetch_detail_exception(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await crawler._fetch_detail("123")
        assert result == {}

    async def test_fetch_price_history_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._fetch_price_history("123")
        assert result == {}

    async def test_fetch_price_history_non_200(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=500, text="error")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_price_history("123")
        assert result == {}

    async def test_fetch_price_history_exception(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(side_effect=RuntimeError("network"))):
            result = await crawler._fetch_price_history("123")
        assert result == {}

    async def test_fetch_detail_success(self):
        crawler = self._make_crawler()
        data = {
            "payload": {
                "publicRecordsInfo": {"ownerName": "JONES BOB"},
                "schoolsInfo": {"servingThisHome": []},
                "walkScore": {},
            }
        }
        resp = _mock_resp(status=200, text=json.dumps(data))
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_detail("999")
        assert result.get("owner_name") == "JONES BOB"

    async def test_fetch_price_history_success(self):
        crawler = self._make_crawler()
        data = {"payload": {"rows": [{"eventName": "Sold", "price": 300000}]}}
        resp = _mock_resp(status=200, text=json.dumps(data))
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_price_history("999")
        assert result == data
