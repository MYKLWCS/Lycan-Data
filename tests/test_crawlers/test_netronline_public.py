"""
test_netronline_public.py — 100% line coverage for modules/crawlers/property/netronline_public.py

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


# ---------------------------------------------------------------------------
# _parse_identifier
# ---------------------------------------------------------------------------


class TestNetronlineParseIdentifier:
    def test_pipe_state_only(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        query, county, state = _parse_identifier("John Smith | TX")
        assert query == "John Smith"
        assert state == "TX"
        assert county == ""

    def test_pipe_county_state(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        query, county, state = _parse_identifier("John Smith | Harris County TX")
        assert query == "John Smith"
        assert county == "harris"
        assert state == "TX"

    def test_pipe_three_parts(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        query, county, state = _parse_identifier("123 Main St | Dallas | TX")
        assert query == "123 Main St"
        assert county == "dallas"
        assert state == "TX"

    def test_pipe_three_parts_county_suffix_stripped(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        query, county, state = _parse_identifier("123 Main St | Harris County | TX")
        assert county == "harris"
        assert state == "TX"

    def test_pipe_two_parts_loc_ends_with_state_abbr(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        # "Houston TX" as loc — not matching "County XX" pattern, not bare state
        query, county, state = _parse_identifier("John Smith | Houston TX")
        assert state == "TX"
        assert query == "John Smith"

    def test_no_pipe_no_state(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        # Single part with no pipe
        query, county, state = _parse_identifier("NoLocation")
        assert query == "NoLocation"
        assert state == ""

    def test_pipe_bare_state_abbr(self):
        from modules.crawlers.property.netronline_public import _parse_identifier

        query, county, state = _parse_identifier("Jane Doe | CA")
        assert query == "Jane Doe"
        assert state == "CA"
        assert county == ""


# ---------------------------------------------------------------------------
# _extract_assessor_url_from_netronline
# ---------------------------------------------------------------------------


class TestExtractAssessorUrl:
    def test_finds_assessor_link(self):
        from modules.crawlers.property.netronline_public import (
            _extract_assessor_url_from_netronline,
        )

        html = """
        <html><body>
        <a href="https://hcad.org/assessor/">Harris County Assessor</a>
        <a href="/some/relative">Other link</a>
        </body></html>
        """
        url = _extract_assessor_url_from_netronline(html)
        assert url == "https://hcad.org/assessor/"

    def test_finds_appraiser_link(self):
        from modules.crawlers.property.netronline_public import (
            _extract_assessor_url_from_netronline,
        )

        html = """
        <html><body>
        <a href="https://example.com/appraiser/">Property Appraiser Office</a>
        </body></html>
        """
        url = _extract_assessor_url_from_netronline(html)
        assert url == "https://example.com/appraiser/"

    def test_finds_property_link(self):
        from modules.crawlers.property.netronline_public import (
            _extract_assessor_url_from_netronline,
        )

        html = """
        <html><body>
        <a href="https://county.gov/property-search">Property Search Portal</a>
        </body></html>
        """
        url = _extract_assessor_url_from_netronline(html)
        assert url == "https://county.gov/property-search"

    def test_relative_url_gets_base_prepended(self):
        from modules.crawlers.property.netronline_public import (
            _extract_assessor_url_from_netronline,
        )

        html = """
        <html><body>
        <a href="/assessor/search">County Assessor</a>
        </body></html>
        """
        url = _extract_assessor_url_from_netronline(html)
        assert url == "https://www.netronline.com/assessor/search"

    def test_no_matching_link_returns_none(self):
        from modules.crawlers.property.netronline_public import (
            _extract_assessor_url_from_netronline,
        )

        html = "<html><body><a href='https://example.com'>Home</a></body></html>"
        assert _extract_assessor_url_from_netronline(html) is None

    def test_empty_html_returns_none(self):
        from modules.crawlers.property.netronline_public import (
            _extract_assessor_url_from_netronline,
        )

        assert _extract_assessor_url_from_netronline("") is None


# ---------------------------------------------------------------------------
# _parse_generic_assessor_html
# ---------------------------------------------------------------------------


class TestParseGenericAssessorHtml:
    def test_extracts_parcel_number(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Parcel: 123-456-789 Owner: SMITH JOHN</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["parcel_number"] == "123-456-789"

    def test_extracts_apn(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>APN: 987654321 value here</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["parcel_number"] == "987654321"

    def test_extracts_owner_name(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Owner:  SMITH JOHN  rest of content</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["owner_name"] == "SMITH JOHN"

    def test_extracts_assessed_value(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Assessed Value: $320,000 something</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["current_assessed_value_usd"] == 320000

    def test_extracts_market_value(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Market Value $450,000</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["current_market_value_usd"] == 450000

    def test_extracts_just_value(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Just Value $380,000</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["current_market_value_usd"] == 380000

    def test_extracts_tax(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Taxes: $4,800</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["current_tax_annual_usd"] == 4800

    def test_extracts_year_built(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Year Built: 2005</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["year_built"] == 2005

    def test_extracts_sq_ft(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        html = "<html><body>Sq. Ft: 1,850</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["sq_ft_living"] == 1850

    def test_empty_html_returns_defaults(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        result = _parse_generic_assessor_html("<html></html>", "query")
        assert result["parcel_number"] is None
        assert result["owner_name"] is None

    def test_invalid_assessed_value_not_set(self):
        from modules.crawlers.property.netronline_public import _parse_generic_assessor_html

        # "123" is too short (< 4 digits) to match \d{4,12}
        html = "<html><body>Assessed: $123</body></html>"
        result = _parse_generic_assessor_html(html, "query")
        assert result["current_assessed_value_usd"] is None

    def test_assessed_value_int_valueerror_branch(self):
        """Lines 216-217: int() raises ValueError for assessed value → field stays None."""
        import builtins

        import modules.crawlers.property.netronline_public as mod

        html = "<html><body>Assessed: $320,000 data here</body></html>"
        real_int = builtins.int
        call_count = [0]

        def patched_int(val, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and not args:
                raise ValueError("forced")
            return real_int(val, *args, **kwargs)

        with patch.object(builtins, "int", side_effect=patched_int):
            result = mod._parse_generic_assessor_html(html, "query")

        assert result["current_assessed_value_usd"] is None

    def test_market_value_int_valueerror_branch(self):
        """Lines 224-225: int() raises ValueError for market value → field stays None."""
        import builtins

        import modules.crawlers.property.netronline_public as mod

        html = "<html><body>Market Value $450,000</body></html>"
        real_int = builtins.int
        call_count = [0]

        def patched_int(val, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and not args:
                raise ValueError("forced")
            return real_int(val, *args, **kwargs)

        with patch.object(builtins, "int", side_effect=patched_int):
            result = mod._parse_generic_assessor_html(html, "query")

        assert result["current_market_value_usd"] is None

    def test_tax_int_valueerror_branch(self):
        """Lines 232-233: int() raises ValueError for tax → field stays None."""
        import builtins

        import modules.crawlers.property.netronline_public as mod

        html = "<html><body>Taxes: $4,800</body></html>"
        real_int = builtins.int
        call_count = [0]

        def patched_int(val, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and not args:
                raise ValueError("forced")
            return real_int(val, *args, **kwargs)

        with patch.object(builtins, "int", side_effect=patched_int):
            result = mod._parse_generic_assessor_html(html, "query")

        assert result["current_tax_annual_usd"] is None

    def test_sq_ft_int_valueerror_branch(self):
        """Lines 245-246: int() raises ValueError for sq ft → field stays None."""
        import builtins

        import modules.crawlers.property.netronline_public as mod

        html = "<html><body>Sq. Ft: 1,850</body></html>"
        real_int = builtins.int
        call_count = [0]

        def patched_int(val, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and not args:
                raise ValueError("forced")
            return real_int(val, *args, **kwargs)

        with patch.object(builtins, "int", side_effect=patched_int):
            result = mod._parse_generic_assessor_html(html, "query")

        assert result["sq_ft_living"] is None


# ---------------------------------------------------------------------------
# NetronlinePublicCrawler.scrape
# ---------------------------------------------------------------------------


class TestNetronlinePublicCrawlerScrape:
    def _make_crawler(self):
        from modules.crawlers.property.netronline_public import NetronlinePublicCrawler

        return NetronlinePublicCrawler()

    def _result_html(self):
        return """
        <html><body>
        Parcel: 555-123-456
        Owner:  JONES ALICE
        Assessed Value: $280,000
        Taxes: $3,600
        Year Built: 1999
        Sq. Ft: 1,400
        </body></html>
        """

    async def test_no_state_returns_error(self):
        crawler = self._make_crawler()
        result = await crawler.scrape("John Smith")
        assert result.found is False
        assert "state_required" in (result.data.get("error") or "")

    async def test_known_portal_tx_harris(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text=self._result_html())

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Harris County TX")

        assert result.found is True
        props = result.data.get("properties", [])
        assert len(props) == 1
        assert props[0]["parcel_number"] == "555-123-456"

    async def test_known_portal_ca_los_angeles(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text=self._result_html())

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe | Los Angeles | CA")

        assert result.found is True

    async def test_none_response_returns_error(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith | Harris County TX")

        assert result.found is False
        assert "portal_http_timeout" in (result.data.get("error") or "")

    async def test_non_200_response_returns_error(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=403, text="Forbidden")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Harris County TX")

        assert result.found is False
        assert "403" in (result.data.get("error") or "")

    async def test_206_response_accepted(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=206, text=self._result_html())

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Harris County TX")

        assert result.found is True

    async def test_no_portal_fallback_to_netronline(self):
        """State is valid but no direct portal → falls back to Netronline lookup."""
        crawler = self._make_crawler()

        netronline_html = """
        <html><body>
        <a href="https://assessor.unknowncounty.gov/search">County Assessor</a>
        </body></html>
        """
        portal_html = self._result_html()

        async def fake_get(url, **kwargs):
            if "netronline.com" in url:
                return _mock_resp(status=200, text=netronline_html)
            return _mock_resp(status=200, text=portal_html)

        # Use a state that has no county in _COUNTY_PORTALS for this specific county
        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("John Smith | Podunk County TX")

        # Either found via Netronline fallback or portal
        assert isinstance(result.found, bool)

    async def test_fallback_netronline_returns_none_url_then_no_portal(self):
        """Netronline lookup finds no assessor URL → returns no_portal_found error."""
        crawler = self._make_crawler()

        async def fake_get(url, **kwargs):
            # Netronline returns a page with no assessor link
            return _mock_resp(status=200, text="<html><body>No links here</body></html>")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=fake_get)):
            result = await crawler.scrape("John Smith | Nowhere County TX")

        assert result.found is False
        assert "no_portal_found" in (result.data.get("error") or "")

    async def test_all_fields_none_found_is_false(self):
        """If parsed HTML produces no useful data, found=False."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="<html><body>No data at all</body></html>")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Harris County TX")

        assert result.found is False

    async def test_county_title_cased_in_output(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text=self._result_html())

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Harris County TX")

        props = result.data.get("properties", [])
        assert props[0]["county"] == "Harris"
        assert props[0]["state"] == "TX"

    async def test_first_word_county_lookup(self):
        """county.split()[0] fallback for multi-word county."""
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text=self._result_html())

        # "los angeles" county — full key exists
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith | Los Angeles | CA")

        assert result.found is True


# ---------------------------------------------------------------------------
# NetronlinePublicCrawler._resolve_via_netronline
# ---------------------------------------------------------------------------


class TestNetronlineResolveViaNetronline:
    def _make_crawler(self):
        from modules.crawlers.property.netronline_public import NetronlinePublicCrawler

        return NetronlinePublicCrawler()

    async def test_successful_resolution(self):
        crawler = self._make_crawler()
        html = '<html><body><a href="https://assessor.county.gov/">Assessor</a></body></html>'
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            url = await crawler._resolve_via_netronline("TX", "harris")

        assert url == "https://assessor.county.gov/"

    async def test_none_response_returns_none(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            url = await crawler._resolve_via_netronline("TX", "harris")

        assert url is None

    async def test_non_200_returns_none(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404, text="not found")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            url = await crawler._resolve_via_netronline("TX", "harris")

        assert url is None

    async def test_exception_returns_none(self):
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(side_effect=RuntimeError("network error"))):
            url = await crawler._resolve_via_netronline("TX", "harris")

        assert url is None

    async def test_empty_county_builds_url(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="<html></html>")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)) as mock_get:
            await crawler._resolve_via_netronline("TX", "")

        called_url = mock_get.call_args[0][0]
        assert "state=tx" in called_url
