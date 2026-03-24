"""
Tests for Property Records scrapers — Tasks 25.
  - PropertyZillowCrawler  (property_zillow)
  - PropertyCountyCrawler  (property_county)

12 tests total — Playwright calls are mocked; no real network traffic.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Trigger @register decorators
import modules.crawlers.property_zillow  # noqa: F401
import modules.crawlers.property_county  # noqa: F401

from modules.crawlers.property_zillow import (
    PropertyZillowCrawler,
    _parse_suggestions,
    _parse_property_page,
)
from modules.crawlers.property_county import (
    PropertyCountyCrawler,
    _parse_identifier,
    _parse_propertyshark_html,
)
from modules.crawlers.registry import is_registered


# ===========================================================================
# Sample fixtures
# ===========================================================================

SAMPLE_SUGGEST_JSON = {
    "results": [
        {
            "display": "123 Main St, Austin, TX 78701",
            "metaData": {
                "addressCity": "Austin",
                "addressState": "TX",
                "addressZip": "78701",
                "lat": 30.267,
                "lng": -97.743,
                "zpid": "12345678",
            },
        },
        {
            "display": "123 Main Ave, Dallas, TX 75201",
            "metaData": {
                "addressCity": "Dallas",
                "addressState": "TX",
                "addressZip": "75201",
                "lat": 32.779,
                "lng": -96.799,
                "zpid": "87654321",
            },
        },
    ]
}

SAMPLE_ZILLOW_HTML = """
<html><head></head><body>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "componentProps": {
        "gdpClientCache": "{}"
      }
    }
  }
}
</script>
<span data-test="zestimate">$450,000</span>
"zestimate":450000,"bedrooms":3,"bathrooms":2.0,"livingArea":1850
</body></html>
"""

SAMPLE_PROPERTYSHARK_HTML = """
<html><body>
<table>
  <tr>
    <td>Owner</td>
    <td>John Smith</td>
  </tr>
  <tr>
    <td>Assessed Value</td>
    <td>$380,000</td>
  </tr>
  <tr>
    <td>Tax Amount</td>
    <td>$5,200</td>
  </tr>
  <tr>
    <td>Year Built</td>
    <td>1995</td>
  </tr>
  <tr>
    <td>Lot Size</td>
    <td>7,500 sqft</td>
  </tr>
  <tr>
    <td>Zoning</td>
    <td>R-1</td>
  </tr>
  <tr>
    <td>Last Sale</td>
    <td>$350,000</td>
  </tr>
  <tr>
    <td>Sale Date</td>
    <td>2020-06-15</td>
  </tr>
</table>
</body></html>
"""

EMPTY_HTML = "<html><body><p>No results found.</p></body></html>"


# ===========================================================================
# 1. Registry tests
# ===========================================================================

def test_property_zillow_registered():
    assert is_registered("property_zillow")


def test_property_county_registered():
    assert is_registered("property_county")


# ===========================================================================
# 2. _parse_suggestions
# ===========================================================================

def test_parse_suggestions_extracts_fields():
    props = _parse_suggestions(SAMPLE_SUGGEST_JSON)
    assert len(props) == 2
    assert props[0]["address"] == "123 Main St, Austin, TX 78701"
    assert props[0]["city"] == "Austin"
    assert props[0]["state"] == "TX"
    assert props[0]["zpid"] == "12345678"


def test_parse_suggestions_empty():
    props = _parse_suggestions({"results": []})
    assert props == []


def test_parse_suggestions_missing_meta():
    data = {"results": [{"display": "No Meta Ave", "metaData": {}}]}
    props = _parse_suggestions(data)
    assert len(props) == 1
    assert props[0]["address"] == "No Meta Ave"
    assert props[0]["city"] == ""


# ===========================================================================
# 3. _parse_property_page
# ===========================================================================

def test_parse_property_page_regex_fallback():
    """Regex patterns extract zestimate / beds / baths / sqft."""
    details = _parse_property_page(SAMPLE_ZILLOW_HTML)
    assert details["zestimate"] == 450000
    assert details["beds"] == 3
    assert details["baths"] == 2.0
    assert details["sqft"] == 1850


def test_parse_property_page_empty_html():
    """Empty page returns all None values, no crash."""
    details = _parse_property_page(EMPTY_HTML)
    for key in ("zestimate", "beds", "baths", "sqft", "last_sold_price", "last_sold_date"):
        assert details[key] is None


# ===========================================================================
# 4. _parse_identifier (county)
# ===========================================================================

def test_parse_identifier_full():
    addr, county, state = _parse_identifier("123 Main St|Cook,IL")
    assert addr == "123 Main St"
    assert county == "Cook"
    assert state == "IL"


def test_parse_identifier_bare_address():
    addr, county, state = _parse_identifier("456 Oak Ave, Houston TX")
    assert addr == "456 Oak Ave, Houston TX"
    assert county == ""
    assert state == ""


# ===========================================================================
# 5. _parse_propertyshark_html
# ===========================================================================

def test_parse_propertyshark_extracts_fields():
    details = _parse_propertyshark_html(SAMPLE_PROPERTYSHARK_HTML)
    # Owner name
    assert details["owner_name"] == "John Smith"
    # Assessed value
    assert details["assessed_value"] == 380000
    # Year built
    assert details["year_built"] == 1995


def test_parse_propertyshark_empty_html():
    details = _parse_propertyshark_html(EMPTY_HTML)
    for key in ("owner_name", "assessed_value", "tax_amount", "year_built"):
        assert details[key] is None


# ===========================================================================
# 6. PropertyZillowCrawler.scrape() — mocked
# ===========================================================================

@pytest.mark.asyncio
async def test_zillow_found():
    """Suggestions returned → found=True, properties list populated."""
    crawler = PropertyZillowCrawler()

    with patch.object(
        crawler, "_fetch_suggestions", new=AsyncMock(return_value=_parse_suggestions(SAMPLE_SUGGEST_JSON))
    ), patch.object(
        crawler, "_fetch_property_page", new=AsyncMock(return_value={"zestimate": 450000, "beds": 3})
    ):
        result = await crawler.scrape("123 Main St Austin TX")

    assert result.found is True
    assert len(result.data["properties"]) == 2
    assert result.data["properties"][0]["zestimate"] == 450000


@pytest.mark.asyncio
async def test_zillow_not_found():
    """No suggestions → found=False."""
    crawler = PropertyZillowCrawler()

    with patch.object(crawler, "_fetch_suggestions", new=AsyncMock(return_value=[])):
        result = await crawler.scrape("Nonexistent Address 99999")

    assert result.found is False
    assert result.data["properties"] == []


# ===========================================================================
# 7. PropertyCountyCrawler.scrape() — mocked
# ===========================================================================

@pytest.mark.asyncio
async def test_county_found():
    """PropertyShark returns data → found=True."""
    crawler = PropertyCountyCrawler()
    parsed = _parse_propertyshark_html(SAMPLE_PROPERTYSHARK_HTML)

    with patch.object(
        crawler, "_scrape_propertyshark", new=AsyncMock(return_value=parsed)
    ):
        result = await crawler.scrape("123 Main St|Cook,IL")

    assert result.found is True
    assert result.data["owner_name"] == "John Smith"
    assert result.data["address"] == "123 Main St"


@pytest.mark.asyncio
async def test_county_not_found():
    """All fields None → found=False."""
    crawler = PropertyCountyCrawler()
    empty = {k: None for k in (
        "owner_name", "assessed_value", "tax_amount", "year_built",
        "lot_size", "zoning", "last_sale_price", "last_sale_date"
    )}

    with patch.object(
        crawler, "_scrape_propertyshark", new=AsyncMock(return_value=empty)
    ):
        result = await crawler.scrape("999 Unknown Blvd|Harris,TX")

    assert result.found is False
