"""
test_property_crawlers_wave3.py — Wave 3 coverage tests.

Targets:
  - people_zabasearch.py    (~24% coverage → _parse_persons, scrape)
  - property_redfin.py      (~31% coverage → _strip_xssi, _parse_autocomplete,
                                             _parse_csv_property, _parse_csv_text,
                                             scrape)
  - property_zillow.py      (uncovered branches → __NEXT_DATA__ extraction,
                                                  _fetch_suggestions, _fetch_property_page)
  - playwright_base.py      (page() async ctx manager, is_blocked())

No real network traffic — all HTTP and Playwright calls are mocked.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Trigger @register decorators so is_registered() works
# ---------------------------------------------------------------------------
import modules.crawlers.people_zabasearch  # noqa: F401
import modules.crawlers.property_redfin  # noqa: F401
import modules.crawlers.property_zillow  # noqa: F401
from modules.crawlers.people_zabasearch import PeopleZabaSearchCrawler, _parse_persons
from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.property_redfin import (
    PropertyRedfinCrawler,
    _parse_autocomplete,
    _parse_csv_property,
    _parse_csv_text,
    _strip_xssi,
)
from modules.crawlers.property_zillow import (
    PropertyZillowCrawler,
    _parse_property_page,
    _parse_suggestions,
)
from modules.crawlers.registry import is_registered


# ---------------------------------------------------------------------------
# Shared mock-response builder
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = "", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


# ===========================================================================
# ZabaSearch — registry
# ===========================================================================


def test_zabasearch_registered():
    assert is_registered("people_zabasearch")


# ===========================================================================
# _parse_persons — HTML shapes
# ===========================================================================


ZABA_HTML_FULL = """
<html><body>
  <div class="person-search-result">
    <h2 class="name">John A Smith</h2>
    <span class="location">Austin, TX</span>
    <span class="age">Age: 42</span>
    <a href="tel:5125550100" class="phone">512-555-0100</a>
  </div>
  <div class="person-search-result">
    <h2>Jane Doe</h2>
    <span class="location">Dallas, TX</span>
    <span class="age">55</span>
    <span class="phone">214-555-0200</span>
  </div>
</body></html>
"""

ZABA_HTML_FALLBACK_CARDS = """
<html><body>
  <div class="search-result">
    <h3>Bob Williams</h3>
    <div class="address">Houston, TX</div>
    <p>Age: 67 | Phone: (713) 555-0300</p>
  </div>
</body></html>
"""

ZABA_HTML_AGE_INLINE = """
<html><body>
  <div class="person-search-result">
    <h2>Mary Jones</h2>
    <span class="city">Denver, CO</span>
    <p>Age 38</p>
  </div>
</body></html>
"""

ZABA_HTML_PHONE_REGEX = """
<html><body>
  <div class="person-search-result">
    <h2>Tom Brown</h2>
    <span class="location">Phoenix, AZ</span>
    <p>Call us at 602.555.0400</p>
  </div>
</body></html>
"""

ZABA_HTML_NO_CITY_STATE = """
<html><body>
  <div class="person-search-result">
    <h2>Alice Green</h2>
    <span class="location">SomeVilleNoComma</span>
  </div>
</body></html>
"""

ZABA_HTML_EMPTY = "<html><body><p>No results.</p></body></html>"

ZABA_HTML_PHONE_TEL_NO_TEXT = """
<html><body>
  <div class="person-search-result">
    <h2>Kevin White</h2>
    <span class="location">Seattle, WA</span>
    <a href="tel:2065550500" class="phone"></a>
  </div>
</body></html>
"""


class TestParsePersons:
    def test_full_card_extracts_all_fields(self):
        persons = _parse_persons(ZABA_HTML_FULL)
        assert len(persons) == 2

        p0 = persons[0]
        assert p0["name"] == "John A Smith"
        assert p0["city"] == "Austin"
        assert p0["state"] == "TX"
        assert p0["age"] == 42
        assert "512-555-0100" in p0["phones"]

        p1 = persons[1]
        assert p1["name"] == "Jane Doe"
        assert p1["city"] == "Dallas"
        assert p1["state"] == "TX"
        assert p1["age"] == 55

    def test_fallback_search_result_cards(self):
        """Falls back to div.search-result when no person-search-result divs."""
        persons = _parse_persons(ZABA_HTML_FALLBACK_CARDS)
        assert len(persons) >= 1
        assert persons[0]["name"] == "Bob Williams"
        assert persons[0]["city"] == "Houston"

    def test_age_inline_text_pattern(self):
        """Parses 'Age 38' from card text when no .age element."""
        persons = _parse_persons(ZABA_HTML_AGE_INLINE)
        assert len(persons) == 1
        assert persons[0]["age"] == 38

    def test_phone_regex_fallback(self):
        """Extracts phone via regex when no phone element is present."""
        persons = _parse_persons(ZABA_HTML_PHONE_REGEX)
        assert len(persons) == 1
        assert persons[0]["phones"] == ["602.555.0400"]

    def test_location_without_state(self):
        """Location string without comma → stored as 'location', not city/state."""
        persons = _parse_persons(ZABA_HTML_NO_CITY_STATE)
        assert len(persons) == 1
        p = persons[0]
        assert "location" in p
        assert "city" not in p
        assert "state" not in p

    def test_phone_from_tel_href_when_text_empty(self):
        """Phone number extracted from href when link text is blank."""
        persons = _parse_persons(ZABA_HTML_PHONE_TEL_NO_TEXT)
        assert len(persons) == 1
        assert "2065550500" in persons[0]["phones"]

    def test_empty_html_returns_empty_list(self):
        persons = _parse_persons(ZABA_HTML_EMPTY)
        assert persons == []

    def test_malformed_html_does_not_raise(self):
        persons = _parse_persons("<<<<not html at all")
        # BeautifulSoup is lenient; may return empty list but must not raise
        assert isinstance(persons, list)

    def test_card_with_no_name_and_no_city_is_skipped(self):
        html = """
        <html><body>
          <div class="person-search-result">
            <span class="age">30</span>
          </div>
        </body></html>
        """
        persons = _parse_persons(html)
        assert persons == []


# ===========================================================================
# PeopleZabaSearchCrawler.scrape() — HTTP responses
# ===========================================================================


class TestZabaSearchScrape:
    def _crawler(self):
        return PeopleZabaSearchCrawler()

    @pytest.mark.asyncio
    async def test_scrape_200_with_results(self):
        crawler = self._crawler()
        mock_resp = _mock_resp(200, text=ZABA_HTML_FULL)
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.platform == "people_zabasearch"
        assert len(result.data["persons"]) == 2

    @pytest.mark.asyncio
    async def test_scrape_200_empty_results(self):
        crawler = self._crawler()
        mock_resp = _mock_resp(200, text=ZABA_HTML_EMPTY)
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
            result = await crawler.scrape("Nobody Here")
        assert result.found is False
        assert result.data["persons"] == []

    @pytest.mark.asyncio
    async def test_scrape_404_returns_not_found(self):
        crawler = self._crawler()
        mock_resp = _mock_resp(404, text="Not Found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error is None  # 404 uses _result(), not CrawlerResult(error=...)

    @pytest.mark.asyncio
    async def test_scrape_429_rate_limited(self):
        crawler = self._crawler()
        mock_resp = _mock_resp(429, text="Too Many Requests")
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_scrape_500_http_error(self):
        crawler = self._crawler()
        mock_resp = _mock_resp(500, text="Server Error")
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "http_500"

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_scrape_single_token_name(self):
        """Identifier with only one word → first='Cher', last=''."""
        crawler = self._crawler()
        mock_resp = _mock_resp(200, text=ZABA_HTML_FULL)
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)) as mock_get:
            await crawler.scrape("Cher")
        # Verify URL was built with empty last name
        called_url = mock_get.call_args[0][0]
        assert "Cher+" in called_url

    @pytest.mark.asyncio
    async def test_scrape_multipart_name_uses_rest_as_last(self):
        """'John James Smith' → first='John', last='James Smith'."""
        crawler = self._crawler()
        mock_resp = _mock_resp(200, text=ZABA_HTML_EMPTY)
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)) as mock_get:
            await crawler.scrape("John James Smith")
        called_url = mock_get.call_args[0][0]
        assert "John" in called_url
        # URL uses raw space (no quote_plus on name parts), last = "James Smith"
        assert "James Smith" in called_url

    @pytest.mark.asyncio
    async def test_scrape_result_includes_profile_url(self):
        crawler = self._crawler()
        mock_resp = _mock_resp(200, text=ZABA_HTML_FULL)
        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
            result = await crawler.scrape("John Smith")
        assert result.profile_url is not None
        assert "zabasearch.com" in result.profile_url


# ===========================================================================
# Redfin — registry
# ===========================================================================


def test_redfin_registered():
    assert is_registered("property_redfin")


# ===========================================================================
# _strip_xssi
# ===========================================================================


class TestStripXssi:
    def test_strips_xssi_prefix(self):
        assert _strip_xssi('{}&&{"payload":{}}') == '{"payload":{}}'

    def test_strips_with_surrounding_spaces(self):
        assert _strip_xssi('  {}  &&  {"a":1}') == '{"a":1}'

    def test_no_xssi_prefix_unchanged(self):
        payload = '{"payload":{"sections":[]}}'
        assert _strip_xssi(payload) == payload

    def test_empty_string(self):
        assert _strip_xssi("") == ""

    def test_only_strips_first_occurrence(self):
        """Only the leading occurrence is stripped."""
        raw = '{}&&{}&&{"nested":true}'
        result = _strip_xssi(raw)
        # The second {}&& should survive
        assert result.startswith("{}&&")


# ===========================================================================
# _parse_autocomplete
# ===========================================================================

AUTOCOMPLETE_PAYLOAD = {
    "payload": {
        "sections": [
            {
                "rows": [
                    {
                        "name": "123 Main St, Austin, TX 78701",
                        "subtext": "Travis County",
                        "url": "/TX/Austin/123-Main-St",
                        "id": "addr_1",
                        "type": "address",
                    },
                    {
                        "name": "123 Main Ave, Dallas, TX",
                        "subtext": "",
                        "url": "/TX/Dallas/123-Main-Ave",
                        "id": "addr_2",
                        "type": "address",
                    },
                ]
            },
            {
                "rows": [
                    {
                        "name": "Main Street Corridor",
                        "subtext": "Neighborhood",
                        "url": "/neighborhood/main-st",
                        "id": "nbr_1",
                        "type": "neighborhood",
                    }
                ]
            },
        ]
    }
}


class TestParseAutocomplete:
    def test_extracts_all_rows_from_all_sections(self):
        items = _parse_autocomplete(AUTOCOMPLETE_PAYLOAD)
        assert len(items) == 3

    def test_first_row_fields(self):
        items = _parse_autocomplete(AUTOCOMPLETE_PAYLOAD)
        first = items[0]
        assert first["address"] == "123 Main St, Austin, TX 78701"
        assert first["subtext"] == "Travis County"
        assert first["url"] == "/TX/Austin/123-Main-St"
        assert first["id"] == "addr_1"
        assert first["type"] == "address"

    def test_empty_payload(self):
        items = _parse_autocomplete({})
        assert items == []

    def test_empty_sections(self):
        items = _parse_autocomplete({"payload": {"sections": []}})
        assert items == []

    def test_section_with_empty_rows(self):
        items = _parse_autocomplete({"payload": {"sections": [{"rows": []}]}})
        assert items == []

    def test_row_with_missing_fields_uses_defaults(self):
        data = {"payload": {"sections": [{"rows": [{}]}]}}
        items = _parse_autocomplete(data)
        assert len(items) == 1
        assert items[0]["address"] == ""
        assert items[0]["id"] == ""
        assert items[0]["type"] == ""


# ===========================================================================
# _parse_csv_property
# ===========================================================================


class TestParseCsvProperty:
    def test_uppercase_column_names(self):
        row = {
            "MLS#": "TX12345",
            "PRICE": "450000",
            "BEDS": "3",
            "BATHS": "2.5",
            "SQFT": "1800",
            "ADDRESS": "123 Main St",
            "YEAR BUILT": "1995",
            "DAYS ON MARKET": "14",
            "LAST SOLD PRICE": "430,000",
            "LAST SOLD DATE": "2023-06-01",
            "STATUS": "Active",
            "URL": "/listing/123",
        }
        prop = _parse_csv_property(row)
        assert prop["mlsId"] == "TX12345"
        assert prop["price"] == 450000.0
        assert prop["beds"] == 3
        assert prop["baths"] == 2.5
        assert prop["sqFt"] == 1800
        assert prop["address"] == "123 Main St"
        assert prop["yearBuilt"] == 1995
        assert prop["daysOnMarket"] == 14
        assert prop["lastSoldPrice"] == 430000.0
        assert prop["lastSoldDate"] == "2023-06-01"
        assert prop["status"] == "Active"
        assert prop["url"] == "/listing/123"

    def test_lowercase_column_names_fallback(self):
        row = {
            "mlsId": "CA99999",
            "price": "600000",
            "beds": "4",
            "baths": "3",
            "sqFt": "2200",
            "address": "456 Oak Ave",
        }
        prop = _parse_csv_property(row)
        assert prop["mlsId"] == "CA99999"
        assert prop["price"] == 600000.0
        assert prop["beds"] == 4

    def test_na_values_return_none(self):
        row = {
            "PRICE": "N/A",
            "BEDS": "N/A",
            "BATHS": "N/A",
            "SQFT": "N/A",
            "YEAR BUILT": "N/A",
        }
        prop = _parse_csv_property(row)
        assert prop["price"] is None
        assert prop["beds"] is None
        assert prop["baths"] is None
        assert prop["sqFt"] is None
        assert prop["yearBuilt"] is None

    def test_empty_strings_return_none(self):
        row = {"PRICE": "", "BEDS": "", "SQFT": ""}
        prop = _parse_csv_property(row)
        assert prop["price"] is None
        assert prop["beds"] is None
        assert prop["sqFt"] is None

    def test_price_with_commas_parsed(self):
        row = {"PRICE": "1,250,000"}
        prop = _parse_csv_property(row)
        assert prop["price"] == 1250000.0

    def test_non_numeric_beds_returns_none(self):
        row = {"BEDS": "Studio"}
        prop = _parse_csv_property(row)
        assert prop["beds"] is None

    def test_empty_row_returns_nones(self):
        prop = _parse_csv_property({})
        assert prop["mlsId"] is None
        assert prop["price"] is None
        assert prop["beds"] is None
        assert prop["address"] == ""


# ===========================================================================
# _parse_csv_text
# ===========================================================================

REDFIN_CSV_TEXT = """MLS#,PRICE,BEDS,BATHS,SQFT,ADDRESS,YEAR BUILT,DAYS ON MARKET,LAST SOLD PRICE,LAST SOLD DATE,STATUS,URL
TX001,350000,3,2,1500,100 Elm St,1990,7,320000,2021-03-15,Active,/tx/elm
TX002,500000,4,3,2100,200 Oak Ave,2005,30,480000,2020-11-20,Active,/tx/oak
"""

REDFIN_JSON_RESPONSE = {
    "payload": {
        "homes": [
            {
                "MLS#": "TX003",
                "PRICE": "275000",
                "BEDS": "2",
                "BATHS": "1",
                "SQFT": "900",
                "ADDRESS": "300 Pine Rd",
                "STATUS": "Pending",
            }
        ]
    }
}

REDFIN_JSON_WITH_ROWS = {
    "payload": {
        "rows": [
            {
                "MLS#": "TX004",
                "PRICE": "180000",
                "BEDS": "2",
                "SQFT": "800",
                "ADDRESS": "400 Cedar Ln",
                "STATUS": "Sold",
            }
        ]
    }
}


class TestParseCsvText:
    def test_plain_csv_parses_two_rows(self):
        props = _parse_csv_text(REDFIN_CSV_TEXT)
        assert len(props) == 2
        assert props[0]["mlsId"] == "TX001"
        assert props[0]["price"] == 350000.0
        assert props[0]["beds"] == 3
        assert props[1]["mlsId"] == "TX002"

    def test_json_payload_with_homes_key(self):
        text = json.dumps(REDFIN_JSON_RESPONSE)
        props = _parse_csv_text(text)
        assert len(props) == 1
        assert props[0]["mlsId"] == "TX003"
        assert props[0]["price"] == 275000.0

    def test_json_payload_with_rows_key(self):
        text = json.dumps(REDFIN_JSON_WITH_ROWS)
        props = _parse_csv_text(text)
        assert len(props) == 1
        assert props[0]["mlsId"] == "TX004"

    def test_json_with_xssi_prefix(self):
        text = "{}&&" + json.dumps(REDFIN_JSON_RESPONSE)
        # _parse_csv_text checks text.strip().startswith("{") — won't match because
        # the text starts with "{}&&". Verify it doesn't crash.
        props = _parse_csv_text(text)
        assert isinstance(props, list)

    def test_empty_csv_returns_empty_list(self):
        props = _parse_csv_text("MLS#,PRICE,BEDS\n")
        assert props == []

    def test_malformed_json_returns_empty_list(self):
        props = _parse_csv_text('{"broken":')
        assert props == []

    def test_empty_string_returns_empty_list(self):
        props = _parse_csv_text("")
        assert props == []


# ===========================================================================
# PropertyRedfinCrawler.scrape()
# ===========================================================================

_REDFIN_AC_TEXT = "{}&&" + json.dumps(
    {
        "payload": {
            "sections": [
                {
                    "rows": [
                        {
                            "name": "123 Main St, Austin, TX",
                            "subtext": "Travis County",
                            "url": "/TX/Austin/123-Main-St",
                            "id": "a1",
                            "type": "address",
                        }
                    ]
                }
            ]
        }
    }
)


class TestRedfinScrape:
    def _crawler(self):
        return PropertyRedfinCrawler()

    @pytest.mark.asyncio
    async def test_scrape_200_both_requests(self):
        crawler = self._crawler()
        ac_resp = _mock_resp(200, text=_REDFIN_AC_TEXT)
        gis_resp = _mock_resp(200, text=REDFIN_CSV_TEXT)

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return ac_resp
            return gis_resp

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St Austin TX")

        assert result.found is True
        assert result.platform == "property_redfin"
        assert len(result.data["properties"]) == 2
        assert len(result.data["autocomplete"]) == 1

    @pytest.mark.asyncio
    async def test_scrape_autocomplete_none_still_proceeds(self):
        """Autocomplete returning None is tolerated; GIS response drives result."""
        crawler = self._crawler()
        gis_resp = _mock_resp(200, text=REDFIN_CSV_TEXT)

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return None
            return gis_resp

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is True
        assert result.data["autocomplete"] == []

    @pytest.mark.asyncio
    async def test_scrape_autocomplete_malformed_json(self):
        """Malformed autocomplete JSON → autocomplete_results is [], scrape continues."""
        crawler = self._crawler()
        ac_resp = _mock_resp(200, text="NOT JSON AT ALL")
        gis_resp = _mock_resp(200, text=REDFIN_CSV_TEXT)

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return ac_resp
            return gis_resp

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is True
        assert result.data["autocomplete"] == []

    @pytest.mark.asyncio
    async def test_scrape_gis_none_returns_http_error(self):
        crawler = self._crawler()
        ac_resp = _mock_resp(200, text=_REDFIN_AC_TEXT)

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return ac_resp
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_scrape_gis_429_rate_limited(self):
        crawler = self._crawler()

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(200, text=_REDFIN_AC_TEXT)
            return _mock_resp(429)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_scrape_gis_403_http_error(self):
        crawler = self._crawler()

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(200, text=_REDFIN_AC_TEXT)
            return _mock_resp(403)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is False
        assert result.error == "http_403"

    @pytest.mark.asyncio
    async def test_scrape_gis_206_partial_content_ok(self):
        """206 Partial Content is treated same as 200."""
        crawler = self._crawler()

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(200, text=_REDFIN_AC_TEXT)
            return _mock_resp(206, text=REDFIN_CSV_TEXT)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_gis_200_empty_csv(self):
        crawler = self._crawler()

        async def _side_effect(url, **kwargs):
            if "autocomplete" in url:
                return _mock_resp(200, text=_REDFIN_AC_TEXT)
            return _mock_resp(200, text="MLS#,PRICE,BEDS\n")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
            result = await crawler.scrape("123 Main St")

        assert result.found is False
        assert result.data["properties"] == []


# ===========================================================================
# Zillow — _parse_property_page (uncovered branches)
# ===========================================================================

NEXT_DATA_WITH_GDP_CACHE = {
    "props": {
        "pageProps": {
            "componentProps": {
                "gdpClientCache": json.dumps(
                    {
                        "key1": {
                            "property": {
                                "zestimate": 550000,
                                "bedrooms": 4,
                                "bathrooms": 3.0,
                                "livingArea": 2400,
                                "priceHistory": [
                                    {"price": 520000, "date": "2022-05-10"},
                                    {"price": 490000, "date": "2019-03-01"},
                                ],
                            }
                        }
                    }
                )
            }
        }
    }
}

NEXT_DATA_WITH_GDP_DIRECT = {
    "props": {
        "pageProps": {
            "componentProps": {
                "gdpClientCache": {
                    "key1": {
                        "zestimate": 620000,
                        "bedrooms": 3,
                        "bathrooms": 2.0,
                        "livingArea": 1950,
                        "priceHistory": [],
                    }
                }
            }
        }
    }
}

NEXT_DATA_NO_MATCHING_KEYS = {
    "props": {
        "pageProps": {
            "componentProps": {
                "gdpClientCache": json.dumps(
                    {
                        "key1": {
                            "someOtherKey": "noPropertyHere"
                        }
                    }
                )
            }
        }
    }
}


def _wrap_next_data(data: dict) -> str:
    return (
        '<html><head></head><body>'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + '</script></body></html>'
    )


class TestParsePropertyPageZillow:
    def test_next_data_with_string_gdp_cache(self):
        """gdpClientCache is a JSON string — parses and extracts property fields."""
        html = _wrap_next_data(NEXT_DATA_WITH_GDP_CACHE)
        details = _parse_property_page(html)
        assert details["zestimate"] == 550000
        assert details["beds"] == 4
        assert details["baths"] == 3.0
        assert details["sqft"] == 2400
        assert details["last_sold_price"] == 520000
        assert details["last_sold_date"] == "2022-05-10"

    def test_next_data_with_dict_gdp_cache(self):
        """gdpClientCache is already a dict — works without inner json.loads."""
        html = _wrap_next_data(NEXT_DATA_WITH_GDP_DIRECT)
        details = _parse_property_page(html)
        assert details["zestimate"] == 620000
        assert details["beds"] == 3
        assert details["baths"] == 2.0
        assert details["sqft"] == 1950
        # Empty priceHistory → last_sold_price stays None
        assert details["last_sold_price"] is None

    def test_next_data_no_matching_property_keys_falls_to_regex(self):
        """gdpClientCache entry has no zestimate/bedrooms → falls back to regex."""
        base_html = _wrap_next_data(NEXT_DATA_NO_MATCHING_KEYS)
        # Append inline JSON so regex can find it
        html = base_html + '"zestimate":399000,"bedrooms":3'
        details = _parse_property_page(html)
        assert details["zestimate"] == 399000
        assert details["beds"] == 3

    def test_no_next_data_script_uses_regex_only(self):
        html = '<html><body>"zestimate":280000,"bedrooms":2,"bathrooms":1.5,"livingArea":1100</body></html>'
        details = _parse_property_page(html)
        assert details["zestimate"] == 280000
        assert details["beds"] == 2
        assert details["baths"] == 1.5
        assert details["sqft"] == 1100

    def test_malformed_next_data_json_falls_back_gracefully(self):
        html = (
            '<html><body>'
            '<script id="__NEXT_DATA__" type="application/json">INVALID{</script>'
            '"zestimate":100000'
            '</body></html>'
        )
        details = _parse_property_page(html)
        # Regex fallback takes over
        assert details["zestimate"] == 100000

    def test_all_none_when_no_data(self):
        details = _parse_property_page("<html><body></body></html>")
        for key in ("zestimate", "beds", "baths", "sqft", "last_sold_price", "last_sold_date"):
            assert details[key] is None


class TestParseSuggestionsZillow:
    def test_respects_max_results_limit(self):
        """Only first 5 results are returned regardless of how many are in the payload."""
        data = {
            "results": [
                {
                    "display": f"Address {i}",
                    "metaData": {
                        "addressCity": "City",
                        "addressState": "TX",
                        "addressZip": "00000",
                        "lat": 0.0,
                        "lng": 0.0,
                        "zpid": str(i),
                    },
                }
                for i in range(10)
            ]
        }
        props = _parse_suggestions(data)
        assert len(props) == 5

    def test_all_detail_fields_are_none_initially(self):
        data = {
            "results": [
                {
                    "display": "789 Elm St",
                    "metaData": {
                        "addressCity": "Reno",
                        "addressState": "NV",
                        "addressZip": "89501",
                        "lat": 39.5,
                        "lng": -119.8,
                        "zpid": "99999",
                    },
                }
            ]
        }
        props = _parse_suggestions(data)
        p = props[0]
        assert p["zestimate"] is None
        assert p["beds"] is None
        assert p["baths"] is None
        assert p["sqft"] is None
        assert p["last_sold_price"] is None
        assert p["last_sold_date"] is None


# ===========================================================================
# PropertyZillowCrawler — _fetch_suggestions / _fetch_property_page
# ===========================================================================


class TestZillowFetchHelpers:
    def _crawler(self):
        return PropertyZillowCrawler()

    @pytest.mark.asyncio
    async def test_fetch_suggestions_valid_json(self):
        """_fetch_suggestions evaluates JS and returns parsed suggestions."""
        crawler = self._crawler()
        suggest_data = {
            "results": [
                {
                    "display": "123 Main St, Austin, TX",
                    "metaData": {
                        "addressCity": "Austin",
                        "addressState": "TX",
                        "addressZip": "78701",
                        "lat": 30.27,
                        "lng": -97.74,
                        "zpid": "11111",
                    },
                }
            ]
        }

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=suggest_data)

        @asynccontextmanager
        async def _fake_page(url=None):
            yield mock_page

        with patch.object(crawler, "page", new=_fake_page):
            props = await crawler._fetch_suggestions("https://fake.url/suggest")

        assert len(props) == 1
        assert props[0]["address"] == "123 Main St, Austin, TX"

    @pytest.mark.asyncio
    async def test_fetch_suggestions_non_dict_response(self):
        """evaluate() returns a non-dict (e.g. None) → returns empty list."""
        crawler = self._crawler()

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=None)

        @asynccontextmanager
        async def _fake_page(url=None):
            yield mock_page

        with patch.object(crawler, "page", new=_fake_page):
            props = await crawler._fetch_suggestions("https://fake.url/suggest")

        assert props == []

    @pytest.mark.asyncio
    async def test_fetch_suggestions_exception_returns_empty(self):
        """Exception inside page context → returns empty list, does not raise."""
        crawler = self._crawler()

        @asynccontextmanager
        async def _failing_page(url=None):
            raise RuntimeError("playwright died")
            yield  # pragma: no cover

        with patch.object(crawler, "page", new=_failing_page):
            props = await crawler._fetch_suggestions("https://fake.url/suggest")

        assert props == []

    @pytest.mark.asyncio
    async def test_fetch_property_page_returns_details(self):
        """_fetch_property_page navigates to a URL and parses the page HTML."""
        crawler = self._crawler()
        html = '<html><body>"zestimate":375000,"bedrooms":3,"bathrooms":2,"livingArea":1600</body></html>'

        mock_page = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value=html)

        @asynccontextmanager
        async def _fake_page(url=None):
            yield mock_page

        with patch.object(crawler, "page", new=_fake_page):
            details = await crawler._fetch_property_page("123 Main St, Austin TX 78701")

        assert details["zestimate"] == 375000
        assert details["beds"] == 3

    @pytest.mark.asyncio
    async def test_fetch_property_page_exception_returns_empty(self):
        """Exception during page navigation → returns empty dict, does not raise."""
        crawler = self._crawler()

        @asynccontextmanager
        async def _failing_page(url=None):
            raise TimeoutError("page timed out")
            yield  # pragma: no cover

        with patch.object(crawler, "page", new=_failing_page):
            details = await crawler._fetch_property_page("Nonexistent Address")

        assert details == {}

    @pytest.mark.asyncio
    async def test_scrape_no_suggestions_returns_not_found(self):
        crawler = self._crawler()
        with patch.object(crawler, "_fetch_suggestions", new=AsyncMock(return_value=[])):
            result = await crawler.scrape("Unknown Address 99999")
        assert result.found is False
        assert result.data["properties"] == []

    @pytest.mark.asyncio
    async def test_scrape_with_suggestions_enriches_first(self):
        crawler = self._crawler()
        suggestions = _parse_suggestions(
            {
                "results": [
                    {
                        "display": "500 Congress Ave, Austin, TX",
                        "metaData": {
                            "addressCity": "Austin",
                            "addressState": "TX",
                            "addressZip": "78701",
                            "lat": 30.27,
                            "lng": -97.74,
                            "zpid": "22222",
                        },
                    }
                ]
            }
        )
        page_details = {"zestimate": 499000, "beds": 2, "baths": 1.0, "sqft": 900}

        with (
            patch.object(crawler, "_fetch_suggestions", new=AsyncMock(return_value=suggestions)),
            patch.object(crawler, "_fetch_property_page", new=AsyncMock(return_value=page_details)),
        ):
            result = await crawler.scrape("500 Congress Ave Austin TX")

        assert result.found is True
        props = result.data["properties"]
        assert props[0]["zestimate"] == 499000
        assert props[0]["beds"] == 2

    @pytest.mark.asyncio
    async def test_scrape_suggestion_no_address_skips_page_fetch(self):
        """Top suggestion with empty 'address' key → _fetch_property_page not called."""
        crawler = self._crawler()
        # Manually craft a suggestion with empty address
        suggestions = [
            {
                "address": "",
                "city": "Austin",
                "state": "TX",
                "zip": "78701",
                "lat": 30.27,
                "lng": -97.74,
                "zpid": "33333",
                "zestimate": None,
                "beds": None,
                "baths": None,
                "sqft": None,
                "last_sold_price": None,
                "last_sold_date": None,
            }
        ]
        mock_fetch_page = AsyncMock(return_value={})

        with (
            patch.object(crawler, "_fetch_suggestions", new=AsyncMock(return_value=suggestions)),
            patch.object(crawler, "_fetch_property_page", new=mock_fetch_page),
        ):
            result = await crawler.scrape("Some Address TX")

        mock_fetch_page.assert_not_called()
        assert result.found is True


# ===========================================================================
# playwright_base.py — page() async context manager
# ===========================================================================


class TestPlaywrightBasePage:
    """
    Tests for PlaywrightCrawler.page() context manager.

    The chain under test:
        async_playwright() -> __aenter__ -> pw
        pw.chromium.launch() -> browser
        browser.new_context() -> context
        context.add_init_script() -> None
        context.new_page() -> page
        page.goto(url) if url provided
        yield page
        browser.close()
    """

    def _make_crawler(self):
        """Minimal concrete subclass of PlaywrightCrawler."""
        from modules.crawlers.result import CrawlerResult

        class _StubCrawler(PlaywrightCrawler):
            platform = "stub_playwright"
            source_reliability = 0.5
            requires_tor = False

            async def scrape(self, identifier: str) -> CrawlerResult:
                return self._result(identifier, found=False)

        return _StubCrawler()

    def _build_pw_mock(self):
        """Build a fully mocked async_playwright() chain."""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html></html>")

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.add_init_script = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw = MagicMock()
        mock_pw.chromium = mock_chromium

        # async_playwright() is used as: async with async_playwright() as pw
        mock_ap_instance = AsyncMock()
        mock_ap_instance.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_ap_instance.__aexit__ = AsyncMock(return_value=False)

        mock_async_playwright = MagicMock(return_value=mock_ap_instance)

        return mock_async_playwright, mock_browser, mock_page

    @pytest.mark.asyncio
    async def test_page_context_manager_yields_page_object(self):
        crawler = self._make_crawler()
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with patch("modules.crawlers.playwright_base.async_playwright", mock_ap):
            async with crawler.page() as page:
                assert page is mock_page

    @pytest.mark.asyncio
    async def test_page_calls_goto_when_url_provided(self):
        crawler = self._make_crawler()
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with patch("modules.crawlers.playwright_base.async_playwright", mock_ap):
            async with crawler.page("https://example.com") as page:
                pass

        mock_page.goto.assert_awaited_once_with(
            "https://example.com", wait_until="domcontentloaded", timeout=30000
        )

    @pytest.mark.asyncio
    async def test_page_does_not_call_goto_without_url(self):
        crawler = self._make_crawler()
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with patch("modules.crawlers.playwright_base.async_playwright", mock_ap):
            async with crawler.page() as page:
                pass

        mock_page.goto.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_page_closes_browser_after_yield(self):
        crawler = self._make_crawler()
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with patch("modules.crawlers.playwright_base.async_playwright", mock_ap):
            async with crawler.page():
                pass

        mock_browser.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_page_closes_browser_on_exception_in_body(self):
        """browser.close() is always called even when the body raises."""
        crawler = self._make_crawler()
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with patch("modules.crawlers.playwright_base.async_playwright", mock_ap):
            with pytest.raises(ValueError, match="body error"):
                async with crawler.page():
                    raise ValueError("body error")

        mock_browser.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_page_uses_proxy_when_available(self):
        """get_proxy() returning a value → browser launched with proxy config."""
        crawler = self._make_crawler()
        crawler.requires_tor = True
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with (
            patch("modules.crawlers.playwright_base.async_playwright", mock_ap),
            patch.object(crawler, "get_proxy", return_value="socks5://127.0.0.1:9050"),
        ):
            async with crawler.page():
                pass

        launch_kwargs = mock_browser.new_context.call_args  # noqa (we check launch args)
        chromium = mock_ap.return_value.__aenter__.return_value.chromium
        launch_call = chromium.launch.call_args
        assert launch_call.kwargs.get("proxy") == {"server": "socks5://127.0.0.1:9050"}

    @pytest.mark.asyncio
    async def test_page_no_proxy_when_get_proxy_returns_none(self):
        crawler = self._make_crawler()
        mock_ap, mock_browser, mock_page = self._build_pw_mock()

        with (
            patch("modules.crawlers.playwright_base.async_playwright", mock_ap),
            patch.object(crawler, "get_proxy", return_value=None),
        ):
            async with crawler.page():
                pass

        chromium = mock_ap.return_value.__aenter__.return_value.chromium
        launch_call = chromium.launch.call_args
        assert launch_call.kwargs.get("proxy") is None


# ===========================================================================
# playwright_base.py — is_blocked()
# ===========================================================================


class TestIsBlocked:
    def _crawler(self):
        from modules.crawlers.result import CrawlerResult

        class _Stub(PlaywrightCrawler):
            platform = "stub"
            source_reliability = 0.5
            requires_tor = False

            async def scrape(self, identifier: str) -> CrawlerResult:
                return self._result(identifier, found=False)

        return _Stub()

    def _page_with_title(self, title_value):
        """Return a mock Page whose title() call returns title_value."""
        mock_page = MagicMock()
        mock_page.title = MagicMock(return_value=title_value)
        return mock_page

    def test_captcha_in_title_is_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("Please complete a CAPTCHA")
        assert crawler.is_blocked(page) is True

    def test_blocked_in_title_is_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("Access Blocked")
        assert crawler.is_blocked(page) is True

    def test_403_in_title_is_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("403 Forbidden")
        assert crawler.is_blocked(page) is True

    def test_access_denied_in_title_is_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("Access Denied - Please Try Again")
        assert crawler.is_blocked(page) is True

    def test_unusual_traffic_in_title_is_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("Our systems have detected unusual traffic")
        assert crawler.is_blocked(page) is True

    def test_normal_title_not_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("123 Main St, Austin TX — Zillow")
        assert crawler.is_blocked(page) is False

    def test_empty_title_not_blocked(self):
        crawler = self._crawler()
        page = self._page_with_title("")
        assert crawler.is_blocked(page) is False

    def test_case_insensitive_matching(self):
        """Block detection is case-insensitive."""
        crawler = self._crawler()
        page = self._page_with_title("CAPTCHA REQUIRED")
        assert crawler.is_blocked(page) is True

    def test_page_without_title_attribute(self):
        """is_blocked() must not raise when title() is unavailable."""
        crawler = self._crawler()
        # MagicMock without title attribute configured — hasattr check handles it
        mock_page = MagicMock(spec=[])  # empty spec → no attributes
        # Should not raise; result should be False (empty string check)
        result = crawler.is_blocked(mock_page)
        assert result is False
