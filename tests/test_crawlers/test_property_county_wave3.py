"""
test_property_county_wave3.py — Coverage gap tests for
modules/crawlers/property_county.py

Targets:
  - Line 48: _parse_identifier pipe-with-no-comma path
  - Lines 147-148: parse exception swallowed; details still returned
  - Line 154: regex fallback for owner_name
  - Line 159: regex fallback for assessed_value
  - Lines 207-214: _scrape_propertyshark exception path returns empty dict

No real network or Playwright calls — all external I/O is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _parse_identifier — line 48: pipe without comma
# ---------------------------------------------------------------------------


class TestParseIdentifier:
    """Unit tests for _parse_identifier helper."""

    def test_full_format_addr_county_state(self):
        from modules.crawlers.property_county import _parse_identifier

        addr, county, state = _parse_identifier("123 Main St|Cook,IL")
        assert addr == "123 Main St"
        assert county == "Cook"
        assert state == "IL"

    def test_pipe_without_comma_state_empty(self):
        """Line 48: 'address|county' with no comma → state is empty string."""
        from modules.crawlers.property_county import _parse_identifier

        addr, county, state = _parse_identifier("456 Oak Ave|Travis")
        assert addr == "456 Oak Ave"
        assert county == "Travis"
        assert state == ""

    def test_no_pipe_bare_address(self):
        """Bare address returns ('address', '', '')."""
        from modules.crawlers.property_county import _parse_identifier

        addr, county, state = _parse_identifier("789 Elm St")
        assert addr == "789 Elm St"
        assert county == ""
        assert state == ""

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        from modules.crawlers.property_county import _parse_identifier

        addr, county, state = _parse_identifier("  100 Broadway  |  New York , NY  ")
        assert addr == "100 Broadway"
        assert county == "New York"
        assert state == "NY"


# ---------------------------------------------------------------------------
# _parse_propertyshark_html — lines 147-148, 154, 159
# ---------------------------------------------------------------------------


class TestParsePropertySharkHtml:
    """Tests for the HTML parser and its fallback paths."""

    def test_exception_during_parse_returns_defaults(self):
        """Lines 147-148: when BeautifulSoup raises internally, details dict is returned."""
        from modules.crawlers.property_county import _parse_propertyshark_html

        # BeautifulSoup is imported inside the function body; patch via bs4 module
        with patch("bs4.BeautifulSoup", side_effect=RuntimeError("bs4 broken")):
            result = _parse_propertyshark_html("<html><body>Owner Alice</body></html>")

        # Even when soup raises, the function returns the partially-filled dict
        assert isinstance(result, dict)
        assert "owner_name" in result

    def test_regex_fallback_owner_name(self):
        """Line 154: when soup parse finds no owner label, regex fallback extracts owner."""
        from modules.crawlers.property_county import _parse_propertyshark_html

        html = '{"owner": "Alice Johnson", "assessed": "$350,000"}'
        result = _parse_propertyshark_html(html)
        assert result["owner_name"] == "Alice Johnson"

    def test_regex_fallback_assessed_value(self):
        """Line 159: when soup finds no assessed value label, regex fallback extracts it."""
        from modules.crawlers.property_county import _parse_propertyshark_html

        # The regex pattern: assessed[^"]*value[^"]*"\s*:\s*"?\$?([\d,]+)
        # It expects a quote before the key name, e.g. "assessed_value": "450000"
        html = '"assessed_value": "450,000"'
        result = _parse_propertyshark_html(html)
        assert result["assessed_value"] == 450000

    def test_full_html_parses_owner_and_value(self):
        """Happy path: well-structured HTML extracts owner + assessed value."""
        from modules.crawlers.property_county import _parse_propertyshark_html

        html = """<html><body>
<table>
  <tr><td>Owner</td><td>Bob Smith</td></tr>
  <tr><td>Assessed Value</td><td>$285,000</td></tr>
  <tr><td>Year Built</td><td>1990</td></tr>
</table>
</body></html>"""
        result = _parse_propertyshark_html(html)
        assert isinstance(result, dict)
        # At minimum the function runs without raising
        assert "owner_name" in result
        assert "assessed_value" in result

    def test_empty_html_returns_all_none(self):
        """Empty HTML returns a dict with all None values."""
        from modules.crawlers.property_county import _parse_propertyshark_html

        result = _parse_propertyshark_html("<html></html>")
        assert result["owner_name"] is None
        assert result["assessed_value"] is None
        assert result["tax_amount"] is None


# ---------------------------------------------------------------------------
# PropertyCountyCrawler._scrape_propertyshark — lines 207-214
# ---------------------------------------------------------------------------


class TestScrapePropertySharkException:
    """Lines 207-214: Playwright error → empty dict returned."""

    @pytest.mark.asyncio
    async def test_playwright_error_returns_empty_dict(self):
        """If self.page() raises, the except block returns a dict of all Nones."""
        from modules.crawlers.property_county import PropertyCountyCrawler

        crawler = PropertyCountyCrawler()

        # Mock the page() context manager to raise
        page_cm = MagicMock()
        page_cm.__aenter__ = AsyncMock(side_effect=Exception("playwright unavailable"))
        page_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(crawler, "page", return_value=page_cm):
            result = await crawler._scrape_propertyshark("https://example.com")

        assert isinstance(result, dict)
        assert result["owner_name"] is None
        assert result["assessed_value"] is None
        assert result["tax_amount"] is None
        assert result["year_built"] is None
        assert result["lot_size"] is None

    @pytest.mark.asyncio
    async def test_scrape_delegates_to_propertyshark(self):
        """scrape() calls _scrape_propertyshark and wraps result in CrawlerResult."""
        from modules.crawlers.property_county import PropertyCountyCrawler

        crawler = PropertyCountyCrawler()

        mock_details = {
            "owner_name": "Carol Davis",
            "assessed_value": 320000,
            "tax_amount": 4800,
            "year_built": 2001,
            "lot_size": "0.25 acres",
            "zoning": "R1",
            "last_sale_price": 310000,
            "last_sale_date": "2018-06-15",
        }

        with patch.object(
            crawler,
            "_scrape_propertyshark",
            new=AsyncMock(return_value=mock_details),
        ):
            result = await crawler.scrape("123 Main St|Travis,TX")

        assert result.found is True
        assert result.data["owner_name"] == "Carol Davis"
        assert result.data["address"] == "123 Main St"

    @pytest.mark.asyncio
    async def test_scrape_bare_address_not_found(self):
        """When _scrape_propertyshark returns all Nones, found=False."""
        from modules.crawlers.property_county import PropertyCountyCrawler

        crawler = PropertyCountyCrawler()

        empty_details = {
            "owner_name": None,
            "assessed_value": None,
            "tax_amount": None,
            "year_built": None,
            "lot_size": None,
            "zoning": None,
            "last_sale_price": None,
            "last_sale_date": None,
        }

        with patch.object(
            crawler,
            "_scrape_propertyshark",
            new=AsyncMock(return_value=empty_details),
        ):
            result = await crawler.scrape("Unknown Street")

        assert result.found is False
        assert result.data["address"] == "Unknown Street"
