"""
Tests for phone enrichment scrapers:
  - CarrierLookupCrawler (phone_carrier)
  - FoneFinderCrawler (phone_fonefinder)
  - TruecallerCrawler (phone_truecaller)

4 tests per scraper = 12 total.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.phone_carrier import CarrierLookupCrawler, parse_phone_parts
from modules.crawlers.phone_fonefinder import FoneFinderCrawler
from modules.crawlers.phone_truecaller import TruecallerCrawler
from modules.crawlers.registry import is_registered

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200, text: str = "", json_data: dict | None = None):
    """Build a fake httpx.Response-like MagicMock."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


# ---------------------------------------------------------------------------
# parse_phone_parts utility
# ---------------------------------------------------------------------------


def test_parse_phone_parts_us_e164():
    parts = parse_phone_parts("+12025551234")
    assert parts["area_code"] == "202"
    assert parts["exchange"] == "555"
    assert parts["last4"] == "1234"
    assert parts["country_code"] == "US"
    assert parts["e164"] == "+12025551234"


def test_parse_phone_parts_us_11digit():
    parts = parse_phone_parts("12025551234")
    assert parts["area_code"] == "202"
    assert parts["country_code"] == "US"


# ---------------------------------------------------------------------------
# Registry checks
# ---------------------------------------------------------------------------


def test_phone_carrier_registered():
    assert is_registered("phone_carrier")


def test_phone_fonefinder_registered():
    assert is_registered("phone_fonefinder")


def test_phone_truecaller_registered():
    assert is_registered("phone_truecaller")


# ---------------------------------------------------------------------------
# CarrierLookupCrawler — 4 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carrier_us_found():
    """US phone returns carrier data when HTML contains carrier info."""
    html = """
    <html><body>
    <table>
      <tr><td>Carrier</td><td>T-Mobile USA</td></tr>
      <tr><td>Type</td><td>Mobile Wireless</td></tr>
    </table>
    </body></html>
    """
    crawler = CarrierLookupCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, html))):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["carrier_name"] != ""
    assert result.data["country_code"] == "US"
    assert result.data["line_type"] == "mobile"
    assert result.platform == "phone_carrier"


@pytest.mark.asyncio
async def test_carrier_not_found_404():
    """404 response returns found=False with not_found error."""
    crawler = CarrierLookupCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(404))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "not_found"


@pytest.mark.asyncio
async def test_carrier_http_error():
    """None response (network failure) returns found=False with http_error."""
    crawler = CarrierLookupCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_carrier_burner_detected():
    """Carrier matching a burner name sets is_burner=True."""
    html = """
    <html><body>
    <table>
      <tr><td>Carrier</td><td>Twilio VoIP Services</td></tr>
      <tr><td>Type</td><td>VOIP</td></tr>
    </table>
    </body></html>
    """
    crawler = CarrierLookupCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, html))):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["is_burner"] is True
    assert result.data["is_voip"] is True


# ---------------------------------------------------------------------------
# FoneFinderCrawler — 4 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fonefinder_us_found():
    """US phone returns carrier and location data from table HTML."""
    html = """
    <html><body>
    <table>
      <tr><td>Carrier</td><td>AT&amp;T Mobility</td></tr>
      <tr><td>Location</td><td>Austin, TX</td></tr>
      <tr><td>Type</td><td>Mobile Wireless</td></tr>
    </table>
    </body></html>
    """
    crawler = FoneFinderCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, html))):
        result = await crawler.scrape("+15125551234")

    assert result.found is True
    assert result.data["carrier_name"] == "AT&T Mobility"
    assert result.data["city"] == "Austin"
    assert result.data["state"] == "TX"
    assert result.platform == "phone_fonefinder"


@pytest.mark.asyncio
async def test_fonefinder_not_found_404():
    """404 response returns found=False."""
    crawler = FoneFinderCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(404))):
        result = await crawler.scrape("+15125551234")

    assert result.found is False
    assert result.error == "not_found"


@pytest.mark.asyncio
async def test_fonefinder_http_error():
    """Network failure (None) returns found=False with http_error."""
    crawler = FoneFinderCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("+15125551234")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_fonefinder_empty_response():
    """200 with no parseable data returns found=False."""
    html = "<html><body><p>No records found.</p></body></html>"
    crawler = FoneFinderCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, html))):
        result = await crawler.scrape("+15125551234")

    assert result.found is False


# ---------------------------------------------------------------------------
# TruecallerCrawler — 4 tests
# ---------------------------------------------------------------------------

_TC_FOUND_JSON = {
    "data": [
        {
            "name": "John Doe",
            "score": 0.85,
            "tags": [{"tag": "spam"}, {"tag": "telemarketer"}],
            "phones": [
                {
                    "carrier": "Verizon Wireless",
                    "type": "MOBILE",
                }
            ],
        }
    ]
}

_TC_EMPTY_JSON = {"data": []}


@pytest.mark.asyncio
async def test_truecaller_found():
    """Valid Truecaller JSON returns name, carrier, score, tags, line_type."""
    crawler = TruecallerCrawler()
    with patch.object(
        crawler,
        "get",
        new=AsyncMock(return_value=_mock_response(200, json_data=_TC_FOUND_JSON)),
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["name"] == "John Doe"
    assert result.data["carrier"] == "Verizon Wireless"
    assert result.data["score"] == 0.85
    assert "spam" in result.data["tags"]
    assert result.data["line_type"] == "mobile"
    assert result.platform == "phone_truecaller"


@pytest.mark.asyncio
async def test_truecaller_not_found_404():
    """404 response returns found=False with not_found error."""
    crawler = TruecallerCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(404))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "not_found"


@pytest.mark.asyncio
async def test_truecaller_http_error():
    """Network failure (None) returns found=False with http_error."""
    crawler = TruecallerCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_truecaller_empty_data():
    """Truecaller returns 200 with empty data list → found=False."""
    crawler = TruecallerCrawler()
    with patch.object(
        crawler,
        "get",
        new=AsyncMock(return_value=_mock_response(200, json_data=_TC_EMPTY_JSON)),
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "no_data"
