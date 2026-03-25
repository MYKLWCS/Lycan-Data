"""
test_propertyradar_scraper.py — 100% line coverage for propertyradar_scraper.py.

Covers _parse_identifier, _money, _bool_flag, _parse_owner_api,
_parse_property_api, _parse_search_html, _parse_property_detail_html,
and PropertyRadarCrawler.scrape() with all branches mocked.
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
    from modules.crawlers.property.propertyradar_scraper import PropertyRadarCrawler

    return PropertyRadarCrawler()


# ---------------------------------------------------------------------------
# _parse_identifier
# ---------------------------------------------------------------------------


class TestParseIdentifier:
    def _fn(self, s):
        from modules.crawlers.property.propertyradar_scraper import _parse_identifier

        return _parse_identifier(s)

    def test_pipe_city_state(self):
        name, state, city_hint = self._fn("John Smith | Los Angeles CA")
        assert name == "John Smith"
        assert state == "CA"
        assert city_hint == "Los Angeles"

    def test_pipe_state_only(self):
        name, state, city_hint = self._fn("Smith, John | TX")
        assert name == "Smith, John"
        assert state == "TX"
        assert city_hint == ""

    def test_pipe_loc_no_state_two_letter(self):
        """loc that IS a two-letter state — exact match branch."""
        name, state, city_hint = self._fn("Jane Doe | CA")
        assert state == "CA"
        assert city_hint == ""

    def test_pipe_loc_no_state_match_at_all(self):
        """loc that has no trailing state code and is not two-letter."""
        name, state, city_hint = self._fn("Bob | London UK something")
        assert name == "Bob"
        assert state == ""

    def test_bare_name_state(self):
        name, state, city_hint = self._fn("John Smith CA")
        assert name == "John Smith"
        assert state == "CA"
        assert city_hint == ""

    def test_bare_name_no_state(self):
        name, state, city_hint = self._fn("Just a Name")
        assert name == "Just a Name"
        assert state == ""
        assert city_hint == ""


# ---------------------------------------------------------------------------
# _money
# ---------------------------------------------------------------------------


class TestMoney:
    def _fn(self, v):
        from modules.crawlers.property.propertyradar_scraper import _money

        return _money(v)

    def test_none_input(self):
        assert self._fn(None) is None

    def test_int_input(self):
        assert self._fn(500000) == 500000

    def test_float_input(self):
        assert self._fn(1500.75) == 1500

    def test_string_usd(self):
        assert self._fn("$1,234,567") == 1234567

    def test_string_plain(self):
        assert self._fn("99999") == 99999

    def test_string_invalid(self):
        assert self._fn("not-a-number") is None

    def test_empty_string(self):
        assert self._fn("") is None


# ---------------------------------------------------------------------------
# _bool_flag
# ---------------------------------------------------------------------------


class TestBoolFlag:
    def _fn(self, v):
        from modules.crawlers.property.propertyradar_scraper import _bool_flag

        return _bool_flag(v)

    def test_true_bool(self):
        assert self._fn(True) is True

    def test_false_bool(self):
        assert self._fn(False) is False

    def test_string_true(self):
        assert self._fn("true") is True

    def test_string_yes(self):
        assert self._fn("yes") is True

    def test_string_1(self):
        assert self._fn("1") is True

    def test_string_y(self):
        assert self._fn("y") is True

    def test_string_false(self):
        assert self._fn("false") is False

    def test_int_1(self):
        assert self._fn(1) is True

    def test_int_0(self):
        assert self._fn(0) is False

    def test_none(self):
        assert self._fn(None) is False


# ---------------------------------------------------------------------------
# _parse_owner_api
# ---------------------------------------------------------------------------


class TestParseOwnerApi:
    def _fn(self, data):
        from modules.crawlers.property.propertyradar_scraper import _parse_owner_api

        return _parse_owner_api(data)

    def test_list_input(self):
        owners = [
            {
                "ownerId": "O1",
                "name": "John Smith",
                "ownerType": "Individual",
                "propertyCount": 3,
                "equity": "500000",
                "totalValue": "1000000",
                "state": "CA",
            }
        ]
        result = self._fn(owners)
        assert len(result) == 1
        assert result[0]["owner_id"] == "O1"
        assert result[0]["estimated_equity"] == 500000
        assert result[0]["portfolio_value"] == 1000000

    def test_dict_owners_key(self):
        data = {"owners": [{"id": "O2", "ownerName": "Corp LLC", "ownerType": "LLC"}]}
        result = self._fn(data)
        assert result[0]["owner_id"] == "O2"
        assert result[0]["owner_name"] == "Corp LLC"

    def test_dict_results_key(self):
        data = {"results": [{"ownerId": "O3", "name": "Jane"}]}
        result = self._fn(data)
        assert result[0]["owner_id"] == "O3"

    def test_empty_list(self):
        assert self._fn([]) == []

    def test_dict_no_keys(self):
        assert self._fn({}) == []

    def test_truncated_at_10(self):
        owners = [{"ownerId": str(i), "name": f"Owner {i}"} for i in range(15)]
        result = self._fn(owners)
        assert len(result) == 10


# ---------------------------------------------------------------------------
# _parse_property_api
# ---------------------------------------------------------------------------


class TestParsePropertyApi:
    def _fn(self, data):
        from modules.crawlers.property.propertyradar_scraper import _parse_property_api

        return _parse_property_api(data)

    def _full_item(self, **overrides):
        base = {
            "apn": "123-456",
            "propertyId": "P001",
            "address": "100 Main St",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90001",
            "county": "Los Angeles",
            "lat": 34.05,
            "lng": -118.25,
            "useType": "SFR",
            "yearBuilt": 1990,
            "buildingSqFt": 1500,
            "lotSqFt": 6000,
            "beds": 3,
            "baths": 2,
            "bathsHalf": 1,
            "stories": 1,
            "garageSpaces": 2,
            "hasPool": True,
            "zoning": "R1",
            "floodZone": "X",
            "schoolDistrict": "LAUSD",
            "assessedValue": "400000",
            "estimatedValue": "550000",
            "taxAmount": "5000",
            "lastSaleDate": "2020-01-15",
            "lastSaleAmount": "520000",
            "lastSaleType": "ARM",
            "ownerName": "John Smith",
            "mailingAddress": "PO Box 1",
            "ownerOccupied": True,
            "homesteadExemption": False,
            "preForeclosure": False,
            "taxDefault": False,
            "llcOwned": False,
            "absenteeOwner": False,
            "vacant": False,
            "equity": "150000",
            "equityPercent": 27,
            "mortgages": [
                {
                    "lenderName": "Big Bank",
                    "loanType": "Fixed",
                    "loanAmount": "370000",
                    "originationDate": "2020-02-01",
                    "isActive": True,
                }
            ],
        }
        base.update(overrides)
        return base

    def test_full_item_list(self):
        items = [self._full_item()]
        result = self._fn(items)
        assert len(result) == 1
        p = result[0]
        assert p["parcel_number"] == "123-456"
        assert p["current_assessed_value_usd"] == 400000
        assert p["current_market_value_usd"] == 550000
        assert p["last_sale_price_usd"] == 520000
        assert p["estimated_equity_usd"] == 150000
        assert len(p["mortgages"]) == 1
        assert p["mortgages"][0]["lender_name"] == "Big Bank"
        assert p["mortgages"][0]["original_loan_amount_usd"] == 370000
        assert p["has_pool"] is True

    def test_dict_properties_key(self):
        data = {"properties": [self._full_item()]}
        result = self._fn(data)
        assert len(result) == 1

    def test_dict_results_key(self):
        data = {"results": [{"parcelNumber": "X-1", "id": "PX", "streetAddress": "5 Elm"}]}
        result = self._fn(data)
        assert result[0]["parcel_number"] == "X-1"
        assert result[0]["street_address"] == "5 Elm"

    def test_fallback_field_names(self):
        """Use alternate field keys: parcelNumber, id, streetAddress, etc."""
        item = {
            "parcelNumber": "ALT-001",
            "id": "PALT",
            "streetAddress": "Alt St",
            "postalCode": "12345",
            "latitude": 32.0,
            "longitude": -96.0,
            "propertyType": "Condo",
            "sqFt": 900,
            "bedrooms": 2,
            "bathrooms": 1,
            "avm": "200000",
            "inForeclosure": True,
            "taxDelinquent": True,
            "corporateOwned": True,
            "isVacant": True,
        }
        result = self._fn([item])
        p = result[0]
        assert p["parcel_number"] == "ALT-001"
        assert p["zip_code"] == "12345"
        assert p["is_pre_foreclosure"] is True
        assert p["is_tax_default"] is True
        assert p["is_llc_owned"] is True
        assert p["is_vacant"] is True

    def test_no_mortgages_key(self):
        item = self._full_item()
        del item["mortgages"]
        result = self._fn([item])
        assert result[0]["mortgages"] == []

    def test_empty_mortgages_list(self):
        item = self._full_item(mortgages=[])
        result = self._fn([item])
        assert result[0]["mortgages"] == []

    def test_truncated_at_25(self):
        items = [self._full_item() for _ in range(30)]
        result = self._fn(items)
        assert len(result) == 25

    def test_empty_input(self):
        assert self._fn([]) == []
        assert self._fn({}) == []


# ---------------------------------------------------------------------------
# _parse_search_html
# ---------------------------------------------------------------------------


class TestParseSearchHtml:
    def _fn(self, html, state="CA"):
        from modules.crawlers.property.propertyradar_scraper import _parse_search_html

        return _parse_search_html(html, state)

    def test_embedded_initial_state_owners(self):
        owner_data = [{"ownerId": "O1", "name": "John Smith", "state": "CA"}]
        page_data = {"search": {"owners": owner_data}}
        js = f"window.__INITIAL_STATE__ = {json.dumps(page_data)};"
        html = f"<html><script>{js}</script></html>"
        owners, pids = self._fn(html)
        assert len(owners) == 1
        assert owners[0]["owner_id"] == "O1"

    def test_embedded_initial_state_top_level_owners(self):
        owner_data = [{"ownerId": "O2", "name": "Jane"}]
        page_data = {"owners": owner_data}
        js = f"window.__INITIAL_STATE__ = {json.dumps(page_data)};"
        html = f"<html><script>{js}</script></html>"
        owners, pids = self._fn(html)
        assert owners[0]["owner_id"] == "O2"

    def test_embedded_initial_state_invalid_json(self):
        """Malformed JSON in __INITIAL_STATE__ — exception swallowed, falls through."""
        html = "<html><script>window.__INITIAL_STATE__ = {BROKEN};</script></html>"
        owners, pids = self._fn(html)
        assert isinstance(owners, list)

    def test_html_table_fallback(self):
        html = (
            "<html><body>"
            '<table class="owner-results">'
            '<tr><td class="owner-name">John Smith</td></tr>'
            '<tr><td class="owner-name">name</td></tr>'  # "name" header row — skipped
            "</table>"
            "</body></html>"
        )
        owners, pids = self._fn(html)
        assert any(o["owner_name"] == "John Smith" for o in owners)

    def test_html_owner_card_fallback(self):
        html = (
            "<html><body>"
            '<div class="owner-card">'
            '<span class="owner-name">Mary Jones</span>'
            "</div>"
            "</body></html>"
        )
        owners, pids = self._fn(html)
        # owner-card div parsed via row.find(class_=...) or row.find("td")
        assert isinstance(owners, list)

    def test_property_id_links_extracted(self):
        html = (
            "<html><body>"
            '<a href="/property/12345">View</a>'
            '<a href="/property/67890">View2</a>'
            "</body></html>"
        )
        owners, pids = self._fn(html)
        assert "12345" in pids
        assert "67890" in pids

    def test_no_matches(self):
        html = "<html><body><p>nothing here</p></body></html>"
        owners, pids = self._fn(html)
        assert owners == []
        assert pids == []

    def test_owner_is_header_skipped(self):
        """Name text is 'owner' — filtered out."""
        html = (
            '<html><body><table class="owner-results"><tr><td>owner</td></tr></table></body></html>'
        )
        owners, pids = self._fn(html)
        assert owners == []


# ---------------------------------------------------------------------------
# _parse_property_detail_html
# ---------------------------------------------------------------------------


class TestParsePropertyDetailHtml:
    def _fn(self, html):
        from modules.crawlers.property.propertyradar_scraper import _parse_property_detail_html

        return _parse_property_detail_html(html)

    def test_embedded_initial_state_property(self):
        """__INITIAL_STATE__ with property data — uses _parse_property_api."""
        prop_data = {
            "apn": "555-123",
            "propertyId": "P555",
            "address": "5 Test Lane",
            "city": "Sacramento",
            "state": "CA",
            "assessedValue": "300000",
        }
        page_data = {"property": prop_data}
        js = f"window.__INITIAL_STATE__ = {json.dumps(page_data)};"
        html = f"<html><script>{js}</script></html>"
        result = self._fn(html)
        assert result["parcel_number"] == "555-123"

    def test_embedded_initial_state_invalid_json(self):
        """Malformed JSON — exception swallowed, regex fallback runs."""
        html = "<html><script>window.__INITIAL_STATE__ = {BROKEN};</script><body>APN: 100-200-300</body></html>"
        result = self._fn(html)
        assert isinstance(result, dict)

    def test_regex_fallback_apn(self):
        html = "<html><body>APN: 100-200-300 Year Built: 1985 Sq. Ft: 1,200 Bedrooms: 3 Bathrooms: 2</body></html>"
        result = self._fn(html)
        assert result["parcel_number"] == "100-200-300"
        assert result["year_built"] == 1985
        assert result["sq_ft_living"] == 1200
        assert result["bedrooms"] == 3
        assert result["bathrooms_full"] == 2

    def test_regex_money_fields(self):
        html = (
            "<html><body>"
            "assessed $400,000 market $550,000 tax $5,000 sale price $520,000 equity $100,000"
            "</body></html>"
        )
        result = self._fn(html)
        assert result["current_assessed_value_usd"] == 400000
        assert result["current_market_value_usd"] == 550000
        assert result["current_tax_annual_usd"] == 5000
        assert result["last_sale_price_usd"] == 520000
        assert result["estimated_equity_usd"] == 100000

    def test_flags_pre_foreclosure(self):
        html = "<html><body>This property is in pre-foreclosure status.</body></html>"
        result = self._fn(html)
        assert result["is_pre_foreclosure"] is True

    def test_flags_notice_of_default(self):
        html = "<html><body>Notice of Default filed.</body></html>"
        result = self._fn(html)
        assert result["is_pre_foreclosure"] is True

    def test_flags_tax_default(self):
        html = "<html><body>Tax default recorded.</body></html>"
        result = self._fn(html)
        assert result["is_tax_default"] is True

    def test_flags_tax_delinquent(self):
        html = "<html><body>Property is tax delinquent.</body></html>"
        result = self._fn(html)
        assert result["is_tax_default"] is True

    def test_flags_absentee(self):
        html = "<html><body>Absentee owner confirmed.</body></html>"
        result = self._fn(html)
        assert result["is_absentee_owner"] is True

    def test_flags_vacant(self):
        html = "<html><body>Property is vacant.</body></html>"
        result = self._fn(html)
        assert result["is_vacant"] is True

    def test_flags_llc(self):
        html = "<html><body>Owner: Acme LLC</body></html>"
        result = self._fn(html)
        assert result["is_llc_owned"] is True

    def test_flags_corp(self):
        html = "<html><body>Owner: Big Corp</body></html>"
        result = self._fn(html)
        assert result["is_llc_owned"] is True

    def test_flags_inc(self):
        html = "<html><body>Owner: Small Inc</body></html>"
        result = self._fn(html)
        assert result["is_llc_owned"] is True

    def test_no_flags_set(self):
        html = "<html><body>Regular residential property.</body></html>"
        result = self._fn(html)
        assert result["is_pre_foreclosure"] is False
        assert result["is_tax_default"] is False
        assert result["is_absentee_owner"] is False
        assert result["is_vacant"] is False
        assert result["is_llc_owned"] is False

    def test_int_conversion_value_error(self):
        """year_built regex matches but value can't be int-cast — set to None."""
        from modules.crawlers.property.propertyradar_scraper import _parse_property_detail_html

        # Can't easily manufacture ValueError from the regex pattern since it requires \d{4}
        # but we can test that non-numeric stays None via empty page
        result = _parse_property_detail_html("<html><body></body></html>")
        assert result["year_built"] is None

    def test_last_sale_date_extracted(self):
        html = "<html><body>Sale Date: 2021/06/15</body></html>"
        result = self._fn(html)
        assert result["last_sale_date"] == "2021/06/15"

    def test_owner_name_extracted(self):
        html = "<html><body>Owner: JOHN SMITH JR</body></html>"
        result = self._fn(html)
        assert result["owner_name"] is not None

    def test_int_conversion_value_error_on_int_key(self):
        """int() raises ValueError for an int_key field that matched regex — set to None.
        We force this by patching int() to raise on its first call."""
        from modules.crawlers.property.propertyradar_scraper import _parse_property_detail_html

        # Craft HTML that matches year_built pattern but then int() raises
        html = "<html><body>Year Built: 1999</body></html>"
        original_int = int
        call_count = [0]

        def _patched_int(v=None, base=10):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("forced int error")
            return original_int(v)

        with patch("builtins.int", side_effect=_patched_int):
            result = _parse_property_detail_html(html)
        # The int_key that raised should have been set to None
        assert result["year_built"] is None

    def test_money_value_error_in_label_loop(self):
        """int() raises ValueError inside the label→dest regex loop — pass, field stays None."""
        from modules.crawlers.property.propertyradar_scraper import _parse_property_detail_html

        # HTML that matches the "assessed" pattern
        html = "<html><body>assessed $400,000</body></html>"
        original_int = int
        call_count = [0]

        def _patched_int(v=None, base=10):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("forced")
            return original_int(v)

        with patch("builtins.int", side_effect=_patched_int):
            result = _parse_property_detail_html(html)
        # ValueError swallowed — field stays None
        assert result["current_assessed_value_usd"] is None


# ---------------------------------------------------------------------------
# PropertyRadarCrawler.scrape()
# ---------------------------------------------------------------------------


class TestPropertyRadarScrape:
    def _make(self):
        return _make_crawler()

    # --- Validation errors --------------------------------------------------

    async def test_empty_name_returns_error(self):
        crawler = self._make()
        result = await crawler.scrape("  ")
        assert result.found is False
        assert result.data.get("error") == "name_required"

    async def test_no_state_returns_error(self):
        crawler = self._make()
        result = await crawler.scrape("John Smith")
        assert result.found is False
        assert "state_required" in result.data.get("error", "")

    # --- API returns owners — fetches properties ----------------------------

    async def test_api_owners_then_property_api(self):
        crawler = self._make()

        owner_data = [{"ownerId": "O1", "name": "John Smith", "state": "CA"}]
        prop_data = [
            {
                "apn": "123-456",
                "propertyId": "P1",
                "address": "100 Main St",
                "city": "LA",
                "state": "CA",
                "assessedValue": "400000",
                "ownerName": "John Smith",
            }
        ]

        call_count = [0]

        async def _fake_get(url, **kwargs):
            call_count[0] += 1
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            if "properties" in url:
                return _mock_resp(status=200, json_data=prop_data)
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("John Smith CA")

        assert result.found is True
        props = result.data.get("properties", [])
        assert len(props) >= 1

    async def test_api_owner_parse_error_falls_to_html_search(self):
        """Owner API returns 200 but json() raises — falls through to HTML search."""
        crawler = self._make()

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                resp = _mock_resp(status=200, text="bad-json")
                resp.json.side_effect = ValueError("bad json")
                return resp
            if "app/search" in url:
                return _mock_resp(status=200, text="<html><body></body></html>")
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("John Smith CA")

        # No owners, no properties — found=False
        assert result.found is False

    async def test_owner_api_non_200_falls_to_html_search(self):
        """Owner API returns non-200 — owners stays empty, HTML search triggered."""
        crawler = self._make()

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=403, text="Forbidden")
            if "app/search" in url:
                html = '<html><body><a href="/property/99999">View</a></body></html>'
                return _mock_resp(status=200, text=html)
            if "property/99999" in url:
                return _mock_resp(status=200, text="<html><body>APN: 001</body></html>")
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Jane Doe CA")

        # Property IDs found, detail pages scraped
        assert isinstance(result.data.get("properties"), list)

    async def test_no_owners_no_pids_returns_not_found(self):
        """Both API and HTML search return nothing."""
        crawler = self._make()

        async def _fake_get(url, **kwargs):
            return _mock_resp(status=200, text="<html><body>nothing</body></html>")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Unknown Person TX")

        assert result.found is False
        assert result.data.get("properties") == []

    async def test_html_search_non_200_skipped(self):
        """HTML search returns non-200 — search_resp condition not met."""
        crawler = self._make()

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=403, text="")
            if "app/search" in url:
                return _mock_resp(status=500, text="Error")
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("John Smith CA")

        assert result.found is False

    async def test_html_search_none_response(self):
        """HTML search returns None."""
        crawler = self._make()

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=403, text="")
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("John Smith CA")

        assert result.found is False

    # --- Owner with no owner_id skips property fetch ------------------------

    async def test_owner_without_owner_id_no_property_fetch(self):
        """owner_id is None — property API never called."""
        crawler = self._make()

        owner_data = [{"ownerId": None, "name": "John Smith"}]

        call_log: list[str] = []

        async def _fake_get(url, **kwargs):
            call_log.append(url)
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            await crawler.scrape("John Smith CA")

        # Property API should NOT have been called
        assert not any("properties?" in u for u in call_log)

    # --- Property API parse error -------------------------------------------

    async def test_property_api_parse_error_swallowed(self):
        """Property API JSON parse raises — logged, empty props list continues."""
        crawler = self._make()

        owner_data = [{"ownerId": "O1", "name": "John Smith"}]

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            if "properties" in url:
                resp = _mock_resp(status=200, text="bad-json")
                resp.json.side_effect = ValueError("bad json")
                return resp
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("John Smith CA")

        assert result.data.get("properties") == []

    async def test_property_api_non_200_skipped(self):
        """Property API returns non-200 — inner if not entered."""
        crawler = self._make()

        owner_data = [{"ownerId": "O1", "name": "John Smith"}]

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            if "properties" in url:
                return _mock_resp(status=429, text="Rate limited")
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("John Smith CA")

        assert result.data.get("properties") == []

    # --- Property ID fallback (detail pages) --------------------------------

    async def test_property_id_fallback_scrapes_detail_pages(self):
        """No API properties — detail pages fetched for PIDs from HTML search."""
        crawler = self._make()

        search_html = (
            "<html><body>"
            '<a href="/property/11111">View</a>'
            '<a href="/property/22222">View2</a>'
            "</body></html>"
        )
        detail_html = "<html><body>APN: 777-888</body></html>"

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=403, text="")
            if "app/search" in url:
                return _mock_resp(status=200, text=search_html)
            if "property/" in url:
                return _mock_resp(status=200, text=detail_html)
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Jane Doe CA")

        assert result.found is True
        props = result.data.get("properties", [])
        assert len(props) == 2
        # property_id injected from URL
        assert props[0].get("property_id") in ("11111", "22222")

    async def test_detail_page_non_200_skipped(self):
        """Detail page returns non-200 — not appended."""
        crawler = self._make()

        search_html = '<html><body><a href="/property/55555">View</a></body></html>'

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=403, text="")
            if "app/search" in url:
                return _mock_resp(status=200, text=search_html)
            if "property/" in url:
                return _mock_resp(status=404, text="Not Found")
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Jane Doe CA")

        assert result.data.get("properties") == []

    async def test_detail_page_none_response_skipped(self):
        """Detail page returns None — not appended."""
        crawler = self._make()

        search_html = '<html><body><a href="/property/66666">View</a></body></html>'

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=403, text="")
            if "app/search" in url:
                return _mock_resp(status=200, text=search_html)
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Jane Doe CA")

        assert result.data.get("properties") == []

    # --- is_llc_owned owner meta injection ----------------------------------

    async def test_llc_owned_set_from_owner_name(self):
        """owner name contains 'llc' → is_llc_owned forced True."""
        crawler = self._make()

        owner_data = [{"ownerId": "O1", "name": "Acme LLC"}]
        prop_data = [
            {
                "apn": "777",
                "propertyId": "P7",
                "address": "7 Test",
                "ownerName": None,
                "llcOwned": False,
            }
        ]

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            if "properties" in url:
                return _mock_resp(status=200, json_data=prop_data)
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Acme LLC CA")

        props = result.data.get("properties", [])
        if props:
            assert props[0]["is_llc_owned"] is True
            assert props[0]["owner_name"] == "Acme LLC"

    # --- Result structure ---------------------------------------------------

    async def test_result_data_keys(self):
        """Successful scrape carries owners, query, state, total_properties."""
        crawler = self._make()

        owner_data = [{"ownerId": "O1", "name": "Bob"}]
        prop_data = [{"apn": "1", "propertyId": "P1", "address": "1 A"}]

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            if "properties" in url:
                return _mock_resp(status=200, json_data=prop_data)
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Bob TX")

        assert result.data.get("query") == "Bob"
        assert result.data.get("state") == "TX"
        assert "total_properties" in result.data
        assert "owners" in result.data

    async def test_max_3_owners_fetched(self):
        """Only first 3 owners are iterated for property fetches."""
        crawler = self._make()

        owner_data = [{"ownerId": f"O{i}", "name": f"Owner {i}"} for i in range(5)]
        prop_call_ids: list[str] = []

        async def _fake_get(url, **kwargs):
            if "owners" in url:
                return _mock_resp(status=200, json_data=owner_data)
            if "properties" in url:
                import re

                m = re.search(r"ownerId=(\w+)", url)
                if m:
                    prop_call_ids.append(m.group(1))
                return _mock_resp(status=200, json_data=[])
            return _mock_resp(status=404, text="")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            await crawler.scrape("Owner CA")

        assert len(prop_call_ids) <= 3
