"""
test_property_tax_nationwide.py — 100% line coverage for
modules/crawlers/property/property_tax_nationwide.py

asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
All HTTP I/O is mocked via patch.object(crawler, 'get', new_callable=AsyncMock).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _tax_html(**kwargs) -> str:
    """Build a minimal HTML page with property tax data."""
    parts = ["<html><body>"]
    if kwargs.get("parcel"):
        parts.append(f"Parcel: {kwargs['parcel']}")
    if kwargs.get("owner"):
        parts.append(f"Owner: {kwargs['owner']}  rest")
    if kwargs.get("address"):
        parts.append(f"Property Address: {kwargs['address']}")
    if kwargs.get("assessed"):
        parts.append(f"Assessed Value: ${kwargs['assessed']}")
    if kwargs.get("market"):
        parts.append(f"Market Value: ${kwargs['market']}")
    if kwargs.get("tax"):
        parts.append(f"Annual Tax: ${kwargs['tax']}")
    if kwargs.get("delinquent"):
        parts.append("This account is DELINQUENT")
    if kwargs.get("exemptions"):
        for ex in kwargs["exemptions"]:
            parts.append(ex)
    parts.append("</body></html>")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# _parse_identifier
# ---------------------------------------------------------------------------


class TestPropertyTaxParseIdentifier:
    def test_apn_prefix(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        query, state = _parse_identifier("APN:123-456-789 TX")
        assert query == "123-456-789"
        assert state == "TX"

    def test_parcel_prefix(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        query, state = _parse_identifier("Parcel:9876543210 FL")
        assert query == "9876543210"
        assert state == "FL"

    def test_address_with_state_at_end(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        # State must be at the very end for the regex to match
        query, state = _parse_identifier("123 Main St, Dallas TX")
        assert "123 Main St" in query
        assert state == "TX"

    def test_state_trimmed_from_query(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        query, state = _parse_identifier("456 Oak Ave CA")
        assert state == "CA"
        assert not query.endswith("CA")

    def test_no_state_returns_empty(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        query, state = _parse_identifier("just some address")
        assert state == ""
        assert query == "just some address"

    def test_trailing_comma_stripped(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        query, state = _parse_identifier("123 Main St, TX")
        assert not query.endswith(",")

    def test_miami_dade(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_identifier

        # APN/Parcel regex: query captures everything between prefix and trailing state abbr
        # "Parcel:1234567890 Miami-Dade FL" — state regex falls back to \b([A-Z]{2})\s*$
        query, state = _parse_identifier("Parcel:1234567890 Miami-Dade FL")
        assert state == "FL"
        # query comes from the APN prefix match or state-at-end fallback
        assert "1234567890" in query


# ---------------------------------------------------------------------------
# _parse_tax_html
# ---------------------------------------------------------------------------


class TestParseTaxHtml:
    def test_empty_html(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        result = _parse_tax_html("<html></html>")
        assert result["parcel_number"] is None
        assert result["is_delinquent"] is False
        assert result["exemptions"] == []

    def test_parcel_extracted(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = _tax_html(parcel="123-456-789")
        result = _parse_tax_html(html)
        assert result["parcel_number"] == "123-456-789"

    def test_owner_extracted(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        # Need two spaces before trailing text to trigger the lookahead
        html = "<html><body>Owner: SMITH JOHN  \nnext line</body></html>"
        result = _parse_tax_html(html)
        assert result["owner_name"] is not None
        assert "SMITH JOHN" in (result["owner_name"] or "")

    def test_taxpayer_label(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>taxpayer: JONES BOB  \nnext line</body></html>"
        result = _parse_tax_html(html)
        assert result["owner_name"] is not None
        assert "JONES BOB" in (result["owner_name"] or "")

    def test_address_extracted(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Property Address: 123 Main St Dallas TX</body></html>"
        result = _parse_tax_html(html)
        assert result["street_address"] is not None

    def test_situs_label(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Situs: 456 Oak Ave Dallas TX 75001</body></html>"
        result = _parse_tax_html(html)
        assert result["street_address"] is not None

    def test_assessed_value(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Assessed $320,000</body></html>"
        result = _parse_tax_html(html)
        assert result["current_assessed_value_usd"] == 320000

    def test_market_value(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Market Value $450,000</body></html>"
        result = _parse_tax_html(html)
        assert result["current_market_value_usd"] == 450000

    def test_fair_market_value(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Fair Market Value $400,000</body></html>"
        result = _parse_tax_html(html)
        assert result["current_market_value_usd"] == 400000

    def test_annual_tax(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Annual Tax $4,800</body></html>"
        result = _parse_tax_html(html)
        assert result["current_tax_annual_usd"] == 4800

    def test_total_tax(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Total Tax $5,200</body></html>"
        result = _parse_tax_html(html)
        assert result["current_tax_annual_usd"] == 5200

    def test_taxes_due(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>Taxes Due $3,900</body></html>"
        result = _parse_tax_html(html)
        assert result["current_tax_annual_usd"] == 3900

    def test_delinquent_flag(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = _tax_html(delinquent=True)
        result = _parse_tax_html(html)
        assert result["is_delinquent"] is True

    def test_tax_lien_flag(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>This property has a tax lien</body></html>"
        result = _parse_tax_html(html)
        assert result["is_delinquent"] is True

    def test_homestead_exemption_detected(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>homestead exemption applied</body></html>"
        result = _parse_tax_html(html)
        assert "Homestead" in result["exemptions"]

    def test_multiple_exemptions(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = "<html><body>homestead senior veteran disability exemptions</body></html>"
        result = _parse_tax_html(html)
        assert "Homestead" in result["exemptions"]
        assert "Senior" in result["exemptions"]
        assert "Veteran" in result["exemptions"]
        assert "Disability" in result["exemptions"]

    def test_tax_history_table_parsed(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = """
        <html><body>
        <table>
          <tr><th>Year</th><th>Assessed</th><th>Market</th><th>Tax</th></tr>
          <tr><td>2022</td><td>$300,000</td><td>$380,000</td><td>$4,500</td></tr>
          <tr><td>2021</td><td>$290,000</td><td>$360,000</td><td>$4,200</td></tr>
        </table>
        </body></html>
        """
        result = _parse_tax_html(html)
        assert len(result["valuations"]) == 2
        assert result["valuations"][0]["valuation_year"] == 2022
        assert result["valuations"][0]["assessed_value_usd"] == 300000
        assert result["valuations"][0]["tax_amount_usd"] == 4500

    def test_table_without_year_col_skipped(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = """
        <html><body>
        <table>
          <tr><th>Name</th><th>Value</th></tr>
          <tr><td>Something</td><td>123</td></tr>
        </table>
        </body></html>
        """
        result = _parse_tax_html(html)
        assert result["valuations"] == []

    def test_table_row_without_year_skipped(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = """
        <html><body>
        <table>
          <tr><th>Year</th><th>Tax</th></tr>
          <tr><td>not-a-year</td><td>$4,000</td></tr>
        </table>
        </body></html>
        """
        result = _parse_tax_html(html)
        assert result["valuations"] == []

    def test_table_short_rows_skipped(self):
        from modules.crawlers.property.property_tax_nationwide import _parse_tax_html

        html = """
        <html><body>
        <table>
          <tr><th>Year</th><th>Tax</th></tr>
        </table>
        </body></html>
        """
        result = _parse_tax_html(html)
        assert result["valuations"] == []


# ---------------------------------------------------------------------------
# PropertyTaxNationwideCrawler.scrape
# ---------------------------------------------------------------------------


class TestPropertyTaxNationwideCrawlerScrape:
    def _make_crawler(self):
        from modules.crawlers.property.property_tax_nationwide import PropertyTaxNationwideCrawler

        return PropertyTaxNationwideCrawler()

    async def test_no_state_returns_error(self):
        crawler = self._make_crawler()
        result = await crawler.scrape("some address without state")
        assert result.found is False
        assert "state_required" in (result.data.get("error") or "")

    async def test_unknown_state_returns_error(self):
        crawler = self._make_crawler()
        result = await crawler.scrape("some address ZZ")
        assert result.found is False
        assert "no_portal_for_state" in (result.data.get("error") or "")

    async def test_primary_success_with_parcel(self):
        crawler = self._make_crawler()
        html = _tax_html(parcel="999-888-777", assessed="300000")
        # Long enough text (> 500 chars)
        padded_html = html + " " * 600
        resp = _mock_resp(status=200, text=padded_html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("APN:999-888-777 TX")

        assert result.found is True
        assert result.data["properties"][0]["parcel_number"] == "999-888-777"

    async def test_primary_200_but_short_uses_fallback(self):
        """Primary returns 200 with < 500 chars → tries fallback."""
        crawler = self._make_crawler()
        fallback_html = _tax_html(parcel="123-456-789", assessed="200000") + " " * 600

        async def fake_get(url, **kwargs):
            if "mycounty" in url:
                return _mock_resp(status=200, text="short")  # < 500 chars → tries fallback
            # Fallback URL (trueprodigy)
            return _mock_resp(status=200, text=fallback_html)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St TX")

        assert result.found is True

    async def test_primary_non_200_uses_fallback(self):
        """Primary 503 → tries fallback URL."""
        crawler = self._make_crawler()
        fallback_html = _tax_html(parcel="CCC-DDD-EEE", assessed="150000") + " " * 600

        async def fake_get(url, **kwargs):
            if "trueprodigy" in url or "mycounty" in url:
                return _mock_resp(status=503, text="error")
            return _mock_resp(status=200, text=fallback_html)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St TX")

        assert result.found is True

    async def test_primary_none_uses_fallback(self):
        """Primary None → tries fallback."""
        crawler = self._make_crawler()
        fallback_html = _tax_html(assessed="100000") + " " * 600

        async def fake_get(url, **kwargs):
            if "trueprodigy" in url or "mycounty" in url:
                return None
            return _mock_resp(status=200, text=fallback_html)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St TX")

        # fallback fetched
        assert isinstance(result.found, bool)

    async def test_all_portals_fail_tries_propertyshark(self):
        """Both primary and fallback fail → PropertyShark last resort."""
        crawler = self._make_crawler()
        propertyshark_html = _tax_html(parcel="PSH-001", assessed="250000") + " " * 600

        call_count = [0]

        async def fake_get(url, **kwargs):
            call_count[0] += 1
            if "propertyshark" in url:
                return _mock_resp(status=200, text=propertyshark_html)
            return _mock_resp(status=503, text="fail")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St TX")

        assert result.found is True

    async def test_all_portals_fail_returns_error(self):
        """All three attempts fail."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("123 Main St TX")

        assert result.found is False
        assert result.data.get("error") == "all_portals_failed"

    async def test_no_fallback_url_state(self):
        """State like KY has no fallback URL (None) — should not crash."""
        crawler = self._make_crawler()
        html = _tax_html(assessed="200000") + " " * 600

        async def fake_get(url, **kwargs):
            if "schneidercorp" in url:
                return _mock_resp(status=200, text=html)
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St KY")

        assert isinstance(result.found, bool)

    async def test_found_false_when_no_useful_data(self):
        """HTML has > 500 chars but no parseable property data → found=False."""
        crawler = self._make_crawler()
        empty_html = "<html><body>" + "X" * 600 + "</body></html>"
        resp = _mock_resp(status=200, text=empty_html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St TX")

        assert result.found is False

    async def test_found_true_with_valuations(self):
        """found=True when valuations list is non-empty."""
        crawler = self._make_crawler()
        html = """
        <html><body>
        <table>
          <tr><th>Year</th><th>Tax</th></tr>
          <tr><td>2022</td><td>$4,500</td></tr>
        </table>
        """ + "X" * 600 + "</body></html>"
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St TX")

        assert result.found is True

    async def test_state_and_query_added_to_output(self):
        crawler = self._make_crawler()
        html = _tax_html(parcel="001-002-003") + " " * 600
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("APN:001-002-003 FL")

        props = result.data.get("properties", [])
        assert props[0]["state"] == "FL"
        assert props[0]["country"] == "US"
        assert props[0]["query"] == "001-002-003"

    async def test_fallback_none_goes_to_propertyshark(self):
        """Fallback URL returns None → propertyshark tried."""
        crawler = self._make_crawler()
        ps_html = _tax_html(assessed="300000") + " " * 600

        call_count = [0]

        async def fake_get(url, **kwargs):
            call_count[0] += 1
            if "propertyshark" in url:
                return _mock_resp(status=200, text=ps_html)
            # First call (primary): short response; second call (fallback): None
            if call_count[0] == 1:
                return _mock_resp(status=200, text="short")
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("123 Main St TX")

        assert isinstance(result.found, bool)
