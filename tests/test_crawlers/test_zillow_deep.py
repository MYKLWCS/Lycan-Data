"""
test_zillow_deep.py — 100% line coverage for modules/crawlers/property/zillow_deep.py

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


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (json.dumps(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ---------------------------------------------------------------------------
# _money
# ---------------------------------------------------------------------------


class TestMoneyHelper:
    def test_none_returns_none(self):
        from modules.crawlers.property.zillow_deep import _money

        assert _money(None) is None

    def test_int_passthrough(self):
        from modules.crawlers.property.zillow_deep import _money

        assert _money(500000) == 500000

    def test_float_truncates(self):
        from modules.crawlers.property.zillow_deep import _money

        assert _money(499999.99) == 499999

    def test_string_with_dollar_and_commas(self):
        from modules.crawlers.property.zillow_deep import _money

        assert _money("$1,250,000") == 1250000

    def test_invalid_string_returns_none(self):
        from modules.crawlers.property.zillow_deep import _money

        assert _money("not-a-number") is None

    def test_empty_string_returns_none(self):
        from modules.crawlers.property.zillow_deep import _money

        assert _money("") is None


# ---------------------------------------------------------------------------
# _parse_suggestions
# ---------------------------------------------------------------------------


class TestParseSuggestions:
    def test_empty_dict(self):
        from modules.crawlers.property.zillow_deep import _parse_suggestions

        assert _parse_suggestions({}) == []

    def test_empty_results(self):
        from modules.crawlers.property.zillow_deep import _parse_suggestions

        assert _parse_suggestions({"results": []}) == []

    def test_full_payload(self):
        from modules.crawlers.property.zillow_deep import _parse_suggestions

        data = {
            "results": [
                {
                    "display": "123 Main St, Dallas, TX 75001",
                    "metaData": {
                        "streetAddress": "123 Main St",
                        "addressCity": "Dallas",
                        "addressState": "TX",
                        "addressZip": "75001",
                        "lat": 32.78,
                        "lng": -96.79,
                        "zpid": 12345,
                    },
                }
            ]
        }
        stubs = _parse_suggestions(data)
        assert len(stubs) == 1
        assert stubs[0]["city"] == "Dallas"
        assert stubs[0]["zpid"] == 12345
        assert stubs[0]["latitude"] == 32.78

    def test_truncates_at_8(self):
        from modules.crawlers.property.zillow_deep import _parse_suggestions

        results = [{"display": f"Addr {i}", "metaData": {}} for i in range(15)]
        stubs = _parse_suggestions({"results": results})
        assert len(stubs) == 8

    def test_missing_meta_fields_default_to_none(self):
        from modules.crawlers.property.zillow_deep import _parse_suggestions

        stubs = _parse_suggestions({"results": [{"display": "X", "metaData": {}}]})
        assert stubs[0]["zpid"] is None
        assert stubs[0]["latitude"] is None


# ---------------------------------------------------------------------------
# _parse_price_history
# ---------------------------------------------------------------------------


class TestParsePriceHistory:
    def test_none_input(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        assert _parse_price_history(None) == []

    def test_empty_list(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        assert _parse_price_history([]) == []

    def test_sold_event_included(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        history = [{"event": "Sold", "price": 400000, "date": "2022-06-01"}]
        result = _parse_price_history(history)
        assert len(result) == 1
        assert result[0]["acquisition_price_usd"] == 400000
        assert result[0]["acquisition_date"] == "2022-06-01"

    def test_non_sold_with_price_included(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        # Has price but not "sold" in event — included because price is truthy
        history = [{"event": "Listed", "price": 350000, "date": "2021-03-01"}]
        result = _parse_price_history(history)
        assert len(result) == 1
        # acquisition_price_usd should be None since neither "sold" nor "bought" in event
        assert result[0]["acquisition_price_usd"] is None

    def test_bought_event_price_set(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        history = [{"event": "Bought", "price": 500000, "date": "2020-01-15"}]
        result = _parse_price_history(history)
        assert len(result) == 1
        assert result[0]["acquisition_price_usd"] == 500000

    def test_no_price_no_sold_excluded(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        history = [{"event": "Price Change", "price": None, "date": "2019-01-01"}]
        result = _parse_price_history(history)
        # price is falsy and "sold" not in event — entry excluded
        assert result == []

    def test_date_fallback_to_time(self):
        from modules.crawlers.property.zillow_deep import _parse_price_history

        history = [{"event": "Sold", "price": 300000, "time": "2018-05-01"}]
        result = _parse_price_history(history)
        assert result[0]["acquisition_date"] == "2018-05-01"


# ---------------------------------------------------------------------------
# _parse_tax_history
# ---------------------------------------------------------------------------


class TestParseTaxHistory:
    def test_none_input(self):
        from modules.crawlers.property.zillow_deep import _parse_tax_history

        assert _parse_tax_history(None) == []

    def test_empty_list(self):
        from modules.crawlers.property.zillow_deep import _parse_tax_history

        assert _parse_tax_history([]) == []

    def test_integer_year(self):
        from modules.crawlers.property.zillow_deep import _parse_tax_history

        history = [{"taxPaidYear": 2021, "value": 320000, "taxPaid": 4800}]
        result = _parse_tax_history(history)
        assert result[0]["valuation_year"] == 2021
        assert result[0]["assessed_value_usd"] == 320000
        assert result[0]["tax_amount_usd"] == 4800

    def test_year_from_timestamp_string(self):
        from modules.crawlers.property.zillow_deep import _parse_tax_history

        history = [{"taxPaidYear": "2020-01-01T00:00:00Z", "value": 300000, "taxPaid": 4200}]
        result = _parse_tax_history(history)
        assert result[0]["valuation_year"] == 2020

    def test_year_fallback_to_time(self):
        from modules.crawlers.property.zillow_deep import _parse_tax_history

        history = [{"time": "2019", "value": 280000, "taxPaid": 3900}]
        result = _parse_tax_history(history)
        assert result[0]["valuation_year"] == 2019

    def test_year_string_no_4digits_becomes_none(self):
        from modules.crawlers.property.zillow_deep import _parse_tax_history

        history = [{"taxPaidYear": "no-year-here", "value": 100000, "taxPaid": 1000}]
        result = _parse_tax_history(history)
        assert result[0]["valuation_year"] is None


# ---------------------------------------------------------------------------
# _parse_next_data
# ---------------------------------------------------------------------------


class TestParseNextData:
    def _make_html(self, home: dict, gdp_cache_raw=None) -> str:
        if gdp_cache_raw is None:
            gdp_cache = {"key1": {"property": home}}
        else:
            gdp_cache = gdp_cache_raw
        page_data = {
            "props": {
                "pageProps": {
                    "componentProps": {"gdpClientCache": json.dumps(gdp_cache)}
                }
            }
        }
        script = json.dumps(page_data)
        return f'<html><script id="__NEXT_DATA__">{script}</script></html>'

    def test_no_script_tag_returns_empty(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        assert _parse_next_data("<html><body>nothing</body></html>") == {}

    def test_basic_home_parsed(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        home = {
            "address": {
                "streetAddress": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "zipcode": "75001",
            },
            "bedrooms": 3,
            "bathrooms": 2.0,
            "livingArea": 1500,
            "zestimate": 450000,
            "yearBuilt": 1998,
        }
        html = self._make_html(home)
        details = _parse_next_data(html)
        assert details["city"] == "Dallas"
        assert details["bedrooms"] == 3
        assert details["zestimate_usd"] == 450000

    def test_home_found_via_bedrooms_key(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        # No "property" wrapper — home directly has "bedrooms"
        home = {"bedrooms": 4, "address": {"city": "Austin", "state": "TX", "streetAddress": "1 Elm St", "zipcode": "78701"}}
        gdp_cache = {"direct_key": home}
        page_data = {
            "props": {
                "pageProps": {
                    "componentProps": {"gdpClientCache": json.dumps(gdp_cache)}
                }
            }
        }
        html = f'<html><script id="__NEXT_DATA__">{json.dumps(page_data)}</script></html>'
        details = _parse_next_data(html)
        assert details.get("bedrooms") == 4

    def test_gdp_cache_as_string_is_parsed(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        home = {
            "address": {"streetAddress": "50 Oak Ave", "city": "Houston", "state": "TX", "zipcode": "77001"},
            "bedrooms": 2,
        }
        gdp_cache = {"k": {"property": home}}
        # gdpClientCache is already a string (double-encoded)
        page_data = {
            "props": {
                "pageProps": {
                    "componentProps": {"gdpClientCache": json.dumps(gdp_cache)}
                }
            }
        }
        html = f'<html><script id="__NEXT_DATA__">{json.dumps(page_data)}</script></html>'
        details = _parse_next_data(html)
        assert details["city"] == "Houston"

    def test_no_home_in_gdp_cache_returns_empty(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        page_data = {
            "props": {
                "pageProps": {
                    "componentProps": {"gdpClientCache": json.dumps({"k": {"other": "data"}})}
                }
            }
        }
        html = f'<html><script id="__NEXT_DATA__">{json.dumps(page_data)}</script></html>'
        assert _parse_next_data(html) == {}

    def test_last_sale_extracted_from_price_history(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        home = {
            "address": {"streetAddress": "1 A St", "city": "A", "state": "TX", "zipcode": "00001"},
            "priceHistory": [
                {"event": "Sold", "price": 380000, "date": "2021-03-01"},
                {"event": "Listed", "price": 390000, "date": "2021-01-01"},
            ],
        }
        html = self._make_html(home)
        details = _parse_next_data(html)
        assert details["last_sale_price_usd"] == 380000
        assert details["last_sale_date"] == "2021-03-01"

    def test_schools_school_district(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        home = {
            "address": {"streetAddress": "2 B St", "city": "B", "state": "TX", "zipcode": "00002"},
            "schools": [{"districtName": "Dallas ISD"}],
        }
        html = self._make_html(home)
        details = _parse_next_data(html)
        assert details["school_district"] == "Dallas ISD"

    def test_has_pool_via_pool_features(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        home = {
            "address": {"streetAddress": "3 C St", "city": "C", "state": "TX", "zipcode": "00003"},
            "poolFeatures": ["In-Ground"],
        }
        html = self._make_html(home)
        details = _parse_next_data(html)
        assert details["has_pool"] is True

    def test_invalid_json_script_returns_empty(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        html = '<html><script id="__NEXT_DATA__">not-valid-json</script></html>'
        assert _parse_next_data(html) == {}

    def test_zestimate_low_percent_parsed(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data

        home = {
            "address": {"streetAddress": "5 E St", "city": "E", "state": "TX", "zipcode": "00005"},
            "zestimate": 300000,
            "zestimateLowPercent": 285000,
        }
        html = self._make_html(home)
        details = _parse_next_data(html)
        assert details["zestimate_low_usd"] == 285000


# ---------------------------------------------------------------------------
# _parse_next_data_fallback_regex
# ---------------------------------------------------------------------------


class TestParseNextDataFallbackRegex:
    def test_extracts_known_fields(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data_fallback_regex

        html = """
        "bedrooms": 4
        "bathrooms": 2.5
        "livingArea": 2000
        "yearBuilt": 2005
        "zestimate": 550000
        "lastSoldPrice": 520000
        "lastSoldDate": "2022-08-15"
        "ownerName": "SMITH JOHN"
        """
        details = _parse_next_data_fallback_regex(html)
        assert details["bedrooms"] == 4
        assert details["bathrooms_full"] == 2.5
        assert details["sq_ft_living"] == 2000
        assert details["year_built"] == 2005
        assert details["current_market_value_usd"] == 550000
        assert details["last_sale_price_usd"] == 520000
        assert details["last_sale_date"] == "2022-08-15"
        assert details["owner_name"] == "SMITH JOHN"

    def test_empty_html_returns_empty_dict(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data_fallback_regex

        assert _parse_next_data_fallback_regex("<html></html>") == {}

    def test_invalid_int_value_kept_as_string(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data_fallback_regex

        # Regex won't match non-digit patterns for int fields anyway; cover int cast path
        html = '"bedrooms": 3 "livingArea": 1800'
        details = _parse_next_data_fallback_regex(html)
        assert details["bedrooms"] == 3

    def test_invalid_float_value_kept_as_string(self):
        from modules.crawlers.property.zillow_deep import _parse_next_data_fallback_regex

        # Patch float() to raise ValueError for bathrooms_full branch
        html = '"bathrooms": abc'
        # abc won't match the regex pattern so result is empty
        details = _parse_next_data_fallback_regex(html)
        assert "bathrooms_full" not in details

    def test_int_conversion_valueerror_branch(self):
        """Lines 269-270: int(val) raises ValueError → val stored as-is."""
        import modules.crawlers.property.zillow_deep as mod

        # Patch int to raise ValueError on the first call (for bedrooms conversion)
        __builtins__["int"] if isinstance(__builtins__, dict) else int
        html = '"bedrooms": 3'

        # Force ValueError by patching the built-in int inside the module
        import builtins
        real_int = builtins.int
        call_count = [0]

        def patched_int(val, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("forced")
            return real_int(val, *args, **kwargs)

        with patch.object(builtins, "int", side_effect=patched_int):
            details = mod._parse_next_data_fallback_regex(html)

        # After ValueError, val ("3") stored directly
        assert details.get("bedrooms") == "3"

    def test_float_conversion_valueerror_branch(self):
        """Lines 274-275: float(val) raises ValueError → val stored as-is."""
        import builtins

        import modules.crawlers.property.zillow_deep as mod

        html = '"bathrooms": 2.5'
        real_float = builtins.float
        call_count = [0]

        def patched_float(val, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("forced float error")
            return real_float(val, *args, **kwargs)

        with patch.object(builtins, "float", side_effect=patched_float):
            details = mod._parse_next_data_fallback_regex(html)

        # After ValueError, val ("2.5") stored directly
        assert details.get("bathrooms_full") == "2.5"


# ---------------------------------------------------------------------------
# ZillowDeepCrawler.scrape
# ---------------------------------------------------------------------------


class TestZillowDeepCrawlerScrape:
    def _make_crawler(self):
        from modules.crawlers.property.zillow_deep import ZillowDeepCrawler

        return ZillowDeepCrawler()

    async def test_none_suggest_response_returns_not_found(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("123 Main St, Dallas TX 75001")
        assert result.found is False
        assert result.data.get("properties") == []

    async def test_non_200_suggest_response_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=403, text="Forbidden")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St, Dallas TX 75001")
        assert result.found is False

    async def test_empty_suggestions_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, json_data={"results": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("unknown address")
        assert result.found is False

    async def test_suggestions_json_parse_error_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="not-json")
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St")
        assert result.found is False

    async def test_successful_scrape_no_zpid(self):
        crawler = self._make_crawler()
        suggest_data = {
            "results": [
                {
                    "display": "123 Main St, Dallas, TX 75001",
                    "metaData": {
                        "streetAddress": "123 Main St",
                        "addressCity": "Dallas",
                        "addressState": "TX",
                        "addressZip": "75001",
                        "lat": 32.78,
                        "lng": -96.79,
                        # no zpid
                    },
                }
            ]
        }
        suggest_resp = _mock_resp(status=200, json_data=suggest_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=suggest_resp)):
            result = await crawler.scrape("123 Main St, Dallas TX 75001")
        assert result.found is True
        assert len(result.data["properties"]) == 1

    async def test_successful_scrape_with_zpid_fetches_page(self):
        crawler = self._make_crawler()
        suggest_data = {
            "results": [
                {
                    "display": "123 Main St",
                    "metaData": {
                        "streetAddress": "123 Main St",
                        "addressCity": "Dallas",
                        "addressState": "TX",
                        "addressZip": "75001",
                        "lat": 32.78,
                        "lng": -96.79,
                        "zpid": 99999,
                    },
                }
            ]
        }

        home = {
            "address": {
                "streetAddress": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "zipcode": "75001",
            },
            "bedrooms": 3,
            "bathrooms": 2.0,
            "zestimate": 450000,
        }
        gdp_cache = {"k": {"property": home}}
        page_data = {
            "props": {
                "pageProps": {"componentProps": {"gdpClientCache": json.dumps(gdp_cache)}}
            }
        }
        page_html = f'<script id="__NEXT_DATA__">{json.dumps(page_data)}</script>'

        suggest_resp = _mock_resp(status=200, json_data=suggest_data)
        page_resp = _mock_resp(status=200, text=page_html)

        call_count = 0

        async def fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return suggest_resp
            return page_resp

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St, Dallas TX 75001")

        assert result.found is True
        assert result.data["properties"][0]["bedrooms"] == 3

    async def test_owner_search_prefix_stripped(self):
        crawler = self._make_crawler()
        suggest_resp = _mock_resp(status=200, json_data={"results": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=suggest_resp)) as mock_get:
            result = await crawler.scrape("owner:John Smith Dallas TX")
        # Verify the "owner:" was stripped from the search term
        called_url = mock_get.call_args[0][0]
        assert "John+Smith" in called_url or "John%20Smith" in called_url
        assert result.found is False

    async def test_scrape_up_to_3_suggestions(self):
        crawler = self._make_crawler()
        suggest_data = {
            "results": [
                {
                    "display": f"Addr {i}",
                    "metaData": {
                        "streetAddress": f"{i} St",
                        "addressCity": "Dallas",
                        "addressState": "TX",
                        "addressZip": "75001",
                        "zpid": None,
                    },
                }
                for i in range(5)
            ]
        }
        suggest_resp = _mock_resp(status=200, json_data=suggest_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=suggest_resp)):
            result = await crawler.scrape("Dallas TX")
        # Only first 3 stubs become properties
        assert len(result.data["properties"]) == 3


# ---------------------------------------------------------------------------
# ZillowDeepCrawler._fetch_property_page
# ---------------------------------------------------------------------------


class TestZillowDeepFetchPropertyPage:
    def _make_crawler(self):
        from modules.crawlers.property.zillow_deep import ZillowDeepCrawler

        return ZillowDeepCrawler()

    async def test_none_response_returns_empty(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._fetch_property_page(12345)
        assert result == {}

    async def test_non_200_returns_empty(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="Not Found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_property_page(12345)
        assert result == {}

    async def test_captcha_page_rotates_circuit_and_returns_empty(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="<html>Please solve the captcha to continue</html>")
        with (
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
        ):
            result = await crawler._fetch_property_page(12345)
        assert result == {}
        mock_rotate.assert_called_once()

    async def test_robot_page_rotates_circuit(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="<html>Are you a robot? Prove it!</html>")
        with (
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
        ):
            result = await crawler._fetch_property_page(99)
        assert result == {}
        mock_rotate.assert_called_once()

    async def test_valid_page_returns_details(self):
        crawler = self._make_crawler()
        home = {
            "address": {"streetAddress": "1 A St", "city": "A", "state": "TX", "zipcode": "00001"},
            "bedrooms": 4,
            "zestimate": 600000,
        }
        gdp_cache = {"k": {"property": home}}
        page_data = {
            "props": {
                "pageProps": {"componentProps": {"gdpClientCache": json.dumps(gdp_cache)}}
            }
        }
        html = f'<script id="__NEXT_DATA__">{json.dumps(page_data)}</script>'
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_property_page(54321)
        assert result["bedrooms"] == 4
        assert result["zpid"] == 54321
        assert "zillow_url" in result

    async def test_fallback_regex_used_when_next_data_empty(self):
        crawler = self._make_crawler()
        # HTML with no __NEXT_DATA__ but with regex-parseable content
        html = '<html><body>"bedrooms": 2 "livingArea": 1200 "zestimate": 200000</body></html>'
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_property_page(11111)
        assert result.get("bedrooms") == 2

    async def test_exception_in_get_returns_empty(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(side_effect=RuntimeError("network error"))):
            result = await crawler._fetch_property_page(99999)
        assert result == {}
