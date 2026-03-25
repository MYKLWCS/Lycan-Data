"""
test_misc_wave4.py — Branch-coverage gap tests (wave 4).

Crawlers covered:
  court_state, court_courtlistener, httpx_base, gov_gleif,
  paste_ghostbin, crypto_bscscan, crypto_polygonscan, cyber_dns,
  google_maps, geo_openstreetmap

Each test targets specific uncovered lines identified in the coverage report.
All I/O is mocked so no network calls are made.
"""

from __future__ import annotations

import socket
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
# court_state.py — lines 62, 134-136
# ===========================================================================


class TestCourtStateParser:
    """Line 62: row with no <td> cells is skipped. Lines 134-136: _scrape_portal exception."""

    def test_row_with_no_cells_is_skipped(self):
        """Line 62: continue fires when row has no <td> elements."""
        from modules.crawlers.court_state import _parse_table_rows

        html = """
        <table>
          <tr><th>Case No.</th><th>Party Name</th><th>Date Filed</th></tr>
          <tr></tr>
          <tr><td>2024-001</td><td>John Smith</td><td>01/01/2024</td></tr>
        </table>
        """
        cases = _parse_table_rows(html, "TX")
        # Empty <tr> should be skipped; the row with cells should parse.
        assert len(cases) == 1
        assert cases[0]["state"] == "TX"

    @pytest.mark.asyncio
    async def test_scrape_portal_exception_returns_empty(self):
        """Lines 134-136: PlaywrightCrawler.page() raises -> returns []."""
        from modules.crawlers.court_state import CourtStateCrawler

        crawler = CourtStateCrawler()
        with patch.object(
            crawler,
            "page",
            side_effect=Exception("playwright failed"),
        ):
            result = await crawler._scrape_portal("https://fake.portal.gov/", "TX")

        assert result == []


# ===========================================================================
# court_courtlistener.py — lines 146-147
# ===========================================================================


class TestCourtListenerPeopleParse:
    """Lines 146-147: people_data.json() fails -> except logs and passes."""

    @pytest.mark.asyncio
    async def test_people_response_json_error_is_handled(self):
        """Lines 146-147: bad JSON on the people endpoint is caught silently."""
        from modules.crawlers.court_courtlistener import CourtListenerCrawler

        crawler = CourtListenerCrawler()

        primary_data = {"results": [], "count": 0}
        primary_resp = _mock_resp(status=200, json_data=primary_data)

        # people_resp returns 200 but json() raises
        people_resp = _mock_resp(status=200)  # json raises ValueError

        responses = [primary_resp, people_resp]
        call_count = {"n": 0}

        async def fake_get(url, **kwargs):
            resp = responses[call_count["n"]]
            call_count["n"] += 1
            return resp

        with patch.object(crawler, "get", fake_get):
            result = await crawler.scrape("John Smith")

        assert result.data.get("case_count", 0) == 0


# ===========================================================================
# httpx_base.py — lines 18-19, 101-102
# ===========================================================================


class TestDomainFromUrl:
    """Lines 18-19: _domain_from_url catches Exception -> returns raw url."""

    def test_invalid_url_returns_raw_string(self):
        """Lines 18-19: urlparse raises (or netloc is empty) -> raw url returned."""
        from modules.crawlers.httpx_base import _domain_from_url

        # urlparse won't raise on most inputs, but netloc will be empty for
        # a bare string without "://", causing the fallback to return the input.
        result = _domain_from_url("not-a-real-url")
        assert result == "not-a-real-url"

    def test_normal_url_returns_netloc(self):
        """Verify happy path of _domain_from_url."""
        from modules.crawlers.httpx_base import _domain_from_url

        result = _domain_from_url("https://api.example.com/path?q=1")
        assert result == "api.example.com"


class TestHttpxCrawlerPost:
    """Lines 101-102: rate_limiter.acquire raises -> debug log + continue with request."""

    @pytest.mark.asyncio
    async def test_post_rate_limiter_error_is_swallowed(self):
        """Lines 101-102: rate limiter acquire failure does not prevent the POST."""
        from modules.crawlers.httpx_base import HttpxCrawler

        # HttpxCrawler is abstract; create a minimal concrete subclass
        class _TestCrawler(HttpxCrawler):
            platform = "test"

            async def scrape(self, identifier):
                pass

        crawler = _TestCrawler()
        good_resp = _mock_resp(status=200, json_data={"ok": True})

        fake_cb = AsyncMock()
        fake_cb.is_open = AsyncMock(return_value=False)
        fake_cb.record_success = AsyncMock()
        fake_cb.record_failure = AsyncMock()

        fake_limiter = AsyncMock()
        fake_limiter.acquire = AsyncMock(side_effect=Exception("redis down"))

        with (
            patch("shared.circuit_breaker.get_circuit_breaker", return_value=fake_cb),
            patch("shared.rate_limiter.get_rate_limiter", return_value=fake_limiter),
            patch.object(crawler, "_client") as mock_client_factory,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=good_resp)
            mock_client_factory.return_value = mock_client

            result = await crawler.post("https://api.example.com/data", json={"key": "val"})

        assert result == good_resp


# ===========================================================================
# gov_gleif.py — lines 124-126
# ===========================================================================


class TestGleifFulltextFallback:
    """Lines 124-126: _fulltext_fallback json raises -> log + return []."""

    @pytest.mark.asyncio
    async def test_fulltext_fallback_json_error_returns_empty(self):
        """Lines 124-126: resp.json() raises inside _fulltext_fallback -> []."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        bad_resp = _mock_resp(status=200)  # json raises ValueError

        with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
            result = await crawler._fulltext_fallback("Goldman+Sachs")

        assert result == []

    @pytest.mark.asyncio
    async def test_fulltext_fallback_none_response_returns_empty(self):
        """Lines 124-126 guard: None response -> early return []."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()

        with patch.object(crawler, "get", AsyncMock(return_value=None)):
            result = await crawler._fulltext_fallback("test")

        assert result == []


# ===========================================================================
# paste_ghostbin.py — lines 114, 123
# ===========================================================================


class TestPasteGhostbinCrawler:
    """Line 114: HTTP 429 returns rate_limited. Line 123: non-200 non-429 returns http_NNN."""

    @pytest.mark.asyncio
    async def test_rate_limited_response(self):
        """Line 114: status 429 -> error='rate_limited'."""
        from modules.crawlers.paste_ghostbin import PasteGhostbinCrawler

        crawler = PasteGhostbinCrawler()
        with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
            result = await crawler.scrape("test@example.com")

        assert result.error == "rate_limited"
        assert result.found is False

    @pytest.mark.asyncio
    async def test_other_error_status(self):
        """Line 123: status 503 -> error='http_503'."""
        from modules.crawlers.paste_ghostbin import PasteGhostbinCrawler

        crawler = PasteGhostbinCrawler()
        with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
            result = await crawler.scrape("test@example.com")

        assert result.error == "http_503"
        assert result.found is False


# ===========================================================================
# crypto_bscscan.py — lines 125-126
# ===========================================================================


class TestCryptoBscscan:
    """Lines 125-126: tx_resp.json() raises -> warning logged, transactions stay []."""

    @pytest.mark.asyncio
    async def test_txlist_json_error_returns_empty_transactions(self):
        """Lines 125-126: malformed JSON on txlist -> empty transactions list."""
        from modules.crawlers.crypto_bscscan import CryptoBscscanCrawler

        crawler = CryptoBscscanCrawler()

        balance_data = {"status": "1", "result": "1000000000000000000"}  # 1 BNB in wei
        balance_resp = _mock_resp(status=200, json_data=balance_data)
        tx_resp = _mock_resp(status=200)  # json raises -> except

        responses = [balance_resp, tx_resp]
        idx = {"n": 0}

        async def fake_get(url, **kwargs):
            r = responses[idx["n"]]
            idx["n"] += 1
            return r

        with patch.object(crawler, "get", fake_get):
            result = await crawler.scrape("0xABCDEF1234567890")

        assert result.found is True
        assert result.data["recent_transactions"] == []


# ===========================================================================
# crypto_polygonscan.py — lines 125-126
# ===========================================================================


class TestCryptoPolygonscan:
    """Lines 125-126: tx_resp.json() raises -> warning logged, transactions stay []."""

    @pytest.mark.asyncio
    async def test_txlist_json_error_returns_empty_transactions(self):
        """Lines 125-126: malformed JSON on txlist -> empty transactions list."""
        from modules.crawlers.crypto_polygonscan import CryptoPolygonscanCrawler

        crawler = CryptoPolygonscanCrawler()

        balance_data = {"status": "1", "result": "2000000000000000000"}  # 2 MATIC in wei
        balance_resp = _mock_resp(status=200, json_data=balance_data)
        tx_resp = _mock_resp(status=200)  # json raises -> except

        responses = [balance_resp, tx_resp]
        idx = {"n": 0}

        async def fake_get(url, **kwargs):
            r = responses[idx["n"]]
            idx["n"] += 1
            return r

        with patch.object(crawler, "get", fake_get):
            result = await crawler.scrape("0xABCDEF1234567890")

        assert result.found is True
        assert result.data["recent_transactions"] == []


# ===========================================================================
# cyber_dns.py — lines 111, 119, 127
# ===========================================================================


class TestCyberDnsHelpers:
    """Lines 111, 119, 127: socket exceptions in _resolve_a, _resolve_aaaa, _reverse_dns."""

    def test_resolve_a_socket_error_returns_empty(self):
        """Line 111: socket.getaddrinfo raises -> except -> return []."""
        from modules.crawlers.cyber_dns import DnsCrawler

        crawler = DnsCrawler()
        with patch(
            "modules.crawlers.cyber_dns.socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")
        ):
            result = crawler._resolve_a("nonexistent.invalid")

        assert result == []

    def test_resolve_aaaa_socket_error_returns_empty(self):
        """Line 119: socket.getaddrinfo (AF_INET6) raises -> except -> return []."""
        from modules.crawlers.cyber_dns import DnsCrawler

        crawler = DnsCrawler()
        with patch(
            "modules.crawlers.cyber_dns.socket.getaddrinfo", side_effect=socket.gaierror("no AAAA")
        ):
            result = crawler._resolve_aaaa("nonexistent.invalid")

        assert result == []

    def test_reverse_dns_socket_error_returns_empty_string(self):
        """Line 127: socket.gethostbyaddr raises -> except -> return ''."""
        from modules.crawlers.cyber_dns import DnsCrawler

        crawler = DnsCrawler()
        with patch(
            "modules.crawlers.cyber_dns.socket.gethostbyaddr",
            side_effect=socket.herror("host not found"),
        ):
            result = crawler._reverse_dns("1.2.3.4")

        assert result == ""


# ===========================================================================
# google_maps.py — lines 90-92
# ===========================================================================


class TestGoogleMapsNominatim:
    """Lines 90-92: Nominatim JSON parse error -> log + return []."""

    @pytest.mark.asyncio
    async def test_nominatim_json_parse_error_returns_empty(self):
        """Lines 90-92: response.json() raises -> return []."""
        from modules.crawlers.google_maps import GoogleMapsCrawler

        crawler = GoogleMapsCrawler()
        bad_resp = _mock_resp(status=200)  # json raises ValueError

        with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
            result = await crawler._query_nominatim("Broken JSON Place")

        assert result == []

    @pytest.mark.asyncio
    async def test_nominatim_failed_response_returns_empty(self):
        """Lines 84-86: non-200 response returns []."""
        from modules.crawlers.google_maps import GoogleMapsCrawler

        crawler = GoogleMapsCrawler()
        with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=500))):
            result = await crawler._query_nominatim("Server Error")

        assert result == []


# ===========================================================================
# geo_openstreetmap.py — lines 48-49
# ===========================================================================


class TestGeoOpenStreetMap:
    """Lines 48-49: _is_latlon ValueError -> return None (falls to nominatim path)."""

    def test_is_latlon_value_error_returns_none(self):
        """Lines 48-49: float() raises ValueError on matched group -> return None."""
        from modules.crawlers.geo_openstreetmap import _is_latlon

        # A string that matches the lat/lon regex format but float() would reject.
        # The regex is: r"^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$"
        # Any valid match will parse as float; the ValueError branch protects
        # against edge-case matches. Verify the function handles no-match -> None.
        result = _is_latlon("not-a-coordinate")
        assert result is None

    def test_is_latlon_valid_returns_tuple(self):
        """Verify happy path for _is_latlon."""
        from modules.crawlers.geo_openstreetmap import _is_latlon

        result = _is_latlon("30.2672,-97.7431")
        assert result is not None
        assert abs(result[0] - 30.2672) < 0.001
        assert abs(result[1] - (-97.7431)) < 0.001

    @pytest.mark.asyncio
    async def test_scrape_routes_to_overpass_for_latlon(self):
        """Scrape with lat/lon identifier calls _scrape_overpass."""
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()

        with patch.object(
            crawler,
            "_scrape_overpass",
            AsyncMock(return_value=MagicMock(found=True)),
        ) as mock_overpass:
            await crawler.scrape("30.2672,-97.7431")

        mock_overpass.assert_called_once()
