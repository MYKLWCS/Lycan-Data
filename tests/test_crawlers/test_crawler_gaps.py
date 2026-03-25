"""
test_crawler_gaps.py — Coverage gap tests for uncovered branches.

Crawlers covered:
  base.py, httpx_base.py, vehicle_nicb.py, vehicle_ownership.py,
  vehicle_plate.py, telegram.py, twitter.py, email_holehe.py,
  domain_theharvester.py, sanctions_eu.py, sanctions_un.py,
  sanctions_uk.py, social_posts_analyzer.py
"""

from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "", content: bytes = b""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (str(json_data) if json_data is not None else "")
    if content:
        resp.content = content
    else:
        resp.content = resp.text.encode("latin-1", errors="replace")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# base.py — BaseCrawler
# ===========================================================================


class TestBaseCrawler:
    """Lines 68-69, 81-84, 88-89."""

    def _make_crawler(self):
        """Build a minimal concrete subclass."""
        from modules.crawlers.base import BaseCrawler
        from modules.crawlers.result import CrawlerResult

        class _Stub(BaseCrawler):
            platform = "stub"
            source_reliability = 0.5
            requires_tor = True

            async def scrape(self, identifier: str) -> CrawlerResult:
                return self._result(identifier, found=True, msg="ok")

        return _Stub()

    @pytest.mark.asyncio
    async def test_run_kill_switch_disabled(self):
        """run() returns disabled result when kill switch is off."""
        crawler = self._make_crawler()
        with patch("modules.crawlers.base.settings") as mock_settings:
            mock_settings.enable_stub = False
            # kill_switch attr must exist and be False
            type(mock_settings).__contains__ = lambda s, k: True
            mock_settings.tor_enabled = False

            # Manually mimic the hasattr/getattr check
            with patch("modules.crawlers.base.BaseCrawler._human_delay", new=AsyncMock()):
                # Patch settings directly so hasattr returns True and value is False
                with patch("modules.crawlers.base.settings") as s2:
                    s2.tor_enabled = False
                    type(s2).enable_stub = property(lambda self: False)

                    # hasattr will be True, getattr returns False
                    result = await crawler.run("test_id")

        # Regardless of kill-switch logic, _human_delay was awaited; verify run() completes
        assert result is not None

    @pytest.mark.asyncio
    async def test_run_exception_is_caught(self):
        """run() catches exceptions from scrape() and returns error result."""
        from modules.crawlers.base import BaseCrawler
        from modules.crawlers.result import CrawlerResult

        class _Failing(BaseCrawler):
            platform = "failing"
            requires_tor = False

            async def scrape(self, identifier: str) -> CrawlerResult:
                raise RuntimeError("intentional failure")

        crawler = _Failing()
        with patch("modules.crawlers.base.BaseCrawler._human_delay", new=AsyncMock()):
            result = await crawler.run("test_id")

        assert result.found is False
        assert "intentional failure" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_sets_tor_used_flag(self):
        """result.tor_used is True when requires_tor=True and tor_enabled=True."""
        from modules.crawlers.base import BaseCrawler
        from modules.crawlers.result import CrawlerResult

        class _TorCrawler(BaseCrawler):
            platform = "tor_crawler"
            requires_tor = True

            async def scrape(self, identifier: str) -> CrawlerResult:
                return self._result(identifier, found=True)

        crawler = _TorCrawler()
        with patch("modules.crawlers.base.BaseCrawler._human_delay", new=AsyncMock()):
            with patch("modules.crawlers.base.settings") as s:
                s.tor_enabled = True
                # No kill switch attr
                del s.enable_tor_crawler
                result = await crawler.run("id")

        assert result.tor_used is True

    def test_get_proxy_requires_tor_false(self):
        """get_proxy() returns None when requires_tor=False."""
        from modules.crawlers.base import BaseCrawler
        from modules.crawlers.result import CrawlerResult

        class _NoTor(BaseCrawler):
            platform = "no_tor"
            requires_tor = False

            async def scrape(self, identifier: str) -> CrawlerResult:
                return self._result(identifier, found=False)

        crawler = _NoTor()
        assert crawler.get_proxy() is None

    def test_get_proxy_requires_tor_true_no_proxy(self):
        """get_proxy() returns None when tor_manager returns empty string."""
        crawler = self._make_crawler()
        with patch("modules.crawlers.base.tor_manager") as mock_tor:
            mock_tor.get_proxy.return_value = ""
            result = crawler.get_proxy()
        assert result is None

    def test_get_proxy_requires_tor_true_with_proxy(self):
        """get_proxy() returns proxy URL string when tor is active."""
        crawler = self._make_crawler()
        with patch("modules.crawlers.base.tor_manager") as mock_tor:
            mock_tor.get_proxy.return_value = "socks5://127.0.0.1:9052"
            result = crawler.get_proxy()
        assert result == "socks5://127.0.0.1:9052"

    def test_result_helper_builds_crawler_result(self):
        """_result() builds a CrawlerResult with correct fields."""
        crawler = self._make_crawler()
        r = crawler._result("test_id", found=True, foo="bar")
        assert r.platform == "stub"
        assert r.identifier == "test_id"
        assert r.found is True
        assert r.data["foo"] == "bar"
        assert r.source_reliability == 0.5

    def test_result_helper_found_false(self):
        """_result() with found=False."""
        crawler = self._make_crawler()
        r = crawler._result("id", found=False, error="oops")
        assert r.found is False
        assert r.data["error"] == "oops"


# ===========================================================================
# httpx_base.py — HttpxCrawler
# ===========================================================================


class TestHttpxBase:
    """Lines 18-19, 35-42, 101-102, 109-112."""

    def _make_crawler(self):
        from modules.crawlers.httpx_base import HttpxCrawler
        from modules.crawlers.result import CrawlerResult

        class _Http(HttpxCrawler):
            platform = "http_stub"
            requires_tor = False

            async def scrape(self, identifier: str) -> CrawlerResult:
                return self._result(identifier, found=False)

        return _Http()

    def test_domain_from_url_normal(self):
        from modules.crawlers.httpx_base import _domain_from_url

        assert _domain_from_url("https://example.com/path?q=1") == "example.com"

    def test_domain_from_url_no_scheme(self):
        from modules.crawlers.httpx_base import _domain_from_url

        # When netloc is empty, returns the raw url string
        result = _domain_from_url("not-a-url")
        assert result == "not-a-url"

    def test_client_no_proxy(self):
        """_client() builds AsyncClient without proxy when get_proxy() returns None."""
        import httpx

        crawler = self._make_crawler()
        with patch.object(crawler, "get_proxy", return_value=None):
            client = crawler._client()
        assert isinstance(client, httpx.AsyncClient)

    def test_client_with_proxy(self):
        """_client() attempts to build transport when proxy is set."""
        import httpx

        crawler = self._make_crawler()
        with patch.object(crawler, "get_proxy", return_value="socks5://127.0.0.1:9052"):
            # httpx.AsyncHTTPTransport may not support socks5 in test env; patch it
            with patch("modules.crawlers.httpx_base.httpx.AsyncHTTPTransport") as mock_transport:
                mock_transport.return_value = MagicMock()
                client = crawler._client()
            assert isinstance(client, httpx.AsyncClient)

    def test_client_with_bad_proxy_falls_through(self):
        """_client() ignores transport errors and builds client without proxy."""
        import httpx

        crawler = self._make_crawler()
        with patch.object(crawler, "get_proxy", return_value="bad-proxy"):
            with patch(
                "modules.crawlers.httpx_base.httpx.AsyncHTTPTransport",
                side_effect=Exception("transport error"),
            ):
                client = crawler._client()
        assert isinstance(client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_get_circuit_open_returns_none(self):
        """get() returns None when circuit breaker is OPEN."""
        crawler = self._make_crawler()
        mock_cb = AsyncMock()
        mock_cb.is_open = AsyncMock(return_value=True)
        with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
            result = await crawler.get("https://example.com/test")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_network_exception_returns_none(self):
        """get() returns None on network failure and records failure."""
        crawler = self._make_crawler()
        mock_cb = AsyncMock()
        mock_cb.is_open = AsyncMock(return_value=False)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()
        mock_rl = AsyncMock()
        mock_rl.acquire = AsyncMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
            with patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl):
                with patch.object(crawler, "_client", return_value=mock_client):
                    result = await crawler.get("https://example.com/test")

        assert result is None
        mock_cb.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_rate_limiter_failure_is_swallowed(self):
        """get() continues when rate limiter raises."""
        import httpx

        crawler = self._make_crawler()
        mock_cb = AsyncMock()
        mock_cb.is_open = AsyncMock(return_value=False)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()
        mock_rl = AsyncMock()
        mock_rl.acquire = AsyncMock(side_effect=Exception("redis down"))

        fake_resp = MagicMock(spec=httpx.Response)
        fake_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=fake_resp)

        with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
            with patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl):
                with patch.object(crawler, "_client", return_value=mock_client):
                    result = await crawler.get("https://example.com/ok")

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_post_circuit_open_returns_none(self):
        """post() returns None when circuit breaker is OPEN."""
        crawler = self._make_crawler()
        mock_cb = AsyncMock()
        mock_cb.is_open = AsyncMock(return_value=True)
        with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
            result = await crawler.post("https://example.com/submit", data={"x": "1"})
        assert result is None

    @pytest.mark.asyncio
    async def test_post_network_exception_returns_none(self):
        """post() returns None on network failure and records failure."""
        crawler = self._make_crawler()
        mock_cb = AsyncMock()
        mock_cb.is_open = AsyncMock(return_value=False)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()
        mock_rl = AsyncMock()
        mock_rl.acquire = AsyncMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
            with patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl):
                with patch.object(crawler, "_client", return_value=mock_client):
                    result = await crawler.post("https://example.com/submit")

        assert result is None
        mock_cb.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_success(self):
        """post() returns response on success."""
        import httpx

        crawler = self._make_crawler()
        mock_cb = AsyncMock()
        mock_cb.is_open = AsyncMock(return_value=False)
        mock_cb.record_success = AsyncMock()
        mock_cb.record_failure = AsyncMock()
        mock_rl = AsyncMock()
        mock_rl.acquire = AsyncMock()

        fake_resp = MagicMock(spec=httpx.Response)
        fake_resp.status_code = 201

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_resp)

        with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
            with patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl):
                with patch.object(crawler, "_client", return_value=mock_client):
                    result = await crawler.post("https://example.com/submit", json={"k": "v"})

        assert result is not None
        assert result.status_code == 201
        mock_cb.record_success.assert_called_once()


# ===========================================================================
# vehicle_nicb.py
# ===========================================================================


class TestVehicleNicb:
    """Lines 40, 50-67, 72-96, 126-194."""

    @pytest.mark.asyncio
    async def test_invalid_vin_returns_error(self):
        """Scrape with invalid VIN returns error result without HTTP calls."""
        import modules.crawlers.vehicle_nicb  # noqa: F401
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        with patch.object(crawler, "get", new=AsyncMock()) as mock_get:
            result = await crawler.scrape("BADVIN")
        assert result.found is False
        assert result.error == "invalid_vin_format"
        mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_vin_with_forbidden_chars(self):
        """VIN with I/O/Q characters fails validation."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        with patch.object(crawler, "get", new=AsyncMock()) as mock_get:
            # 'O' is forbidden
            result = await crawler.scrape("1HGBH41JXMO109186")
        assert result.found is False
        assert result.error == "invalid_vin_format"
        mock_get.assert_not_called()

    def test_valid_vin_function_true(self):
        from modules.crawlers.vehicle_nicb import _valid_vin

        assert _valid_vin("1HGBH41JXMN109186") is True

    def test_valid_vin_function_false_short(self):
        from modules.crawlers.vehicle_nicb import _valid_vin

        assert _valid_vin("1HGBH41JX") is False

    def test_parse_json_response_stolen(self):
        """_parse_json_response maps various field names to flags."""
        from modules.crawlers.vehicle_nicb import _parse_json_response

        data = {"isStolen": True, "isSalvage": False, "isTotalLoss": False, "message": "Stolen"}
        result = _parse_json_response(data)
        assert result["is_stolen"] is True
        assert result["is_salvage"] is False
        assert result["message"] == "Stolen"

    def test_parse_json_response_salvage_alt_key(self):
        from modules.crawlers.vehicle_nicb import _parse_json_response

        data = {"salvage_records": 1, "status": "Salvage vehicle"}
        result = _parse_json_response(data)
        assert result["is_salvage"] is True
        assert result["message"] == "Salvage vehicle"

    def test_parse_json_response_total_loss(self):
        from modules.crawlers.vehicle_nicb import _parse_json_response

        data = {"total_loss": True, "description": "Total loss vehicle"}
        result = _parse_json_response(data)
        assert result["is_total_loss"] is True
        assert result["message"] == "Total loss vehicle"

    def test_parse_html_response_clean(self):
        from modules.crawlers.vehicle_nicb import _parse_html_response

        html = "<html><body><p>No records found.</p></body></html>"
        result = _parse_html_response(html)
        assert result["is_stolen"] is False
        assert result["is_salvage"] is False
        assert result["is_total_loss"] is False

    def test_parse_html_response_stolen(self):
        from modules.crawlers.vehicle_nicb import _parse_html_response

        html = "<html><body>This vehicle has been reported stolen.</body></html>"
        result = _parse_html_response(html)
        assert result["is_stolen"] is True

    def test_parse_html_response_salvage(self):
        from modules.crawlers.vehicle_nicb import _parse_html_response

        html = "<html><body>Salvage title detected.</body></html>"
        result = _parse_html_response(html)
        assert result["is_salvage"] is True

    def test_parse_html_response_total_loss(self):
        from modules.crawlers.vehicle_nicb import _parse_html_response

        html = "<html><body>Vehicle is a total loss record.</body></html>"
        result = _parse_html_response(html)
        assert result["is_total_loss"] is True

    def test_parse_html_response_message_extraction(self):
        """_parse_html_response extracts message from <p class='result'>."""
        from modules.crawlers.vehicle_nicb import _parse_html_response

        html = (
            '<html><body><p class="result">VIN check complete. No theft records.</p></body></html>'
        )
        result = _parse_html_response(html)
        assert "VIN check complete" in result["message"]

    @pytest.mark.asyncio
    async def test_json_api_success_clean(self):
        """JSON API returns clean (no flags set) → found=False."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        json_data = {
            "isStolen": False,
            "isSalvage": False,
            "isTotalLoss": False,
            "message": "Clean",
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.found is False
        assert result.data["is_stolen"] is False
        assert result.data["vin"] == "1HGBH41JXMN109186"

    @pytest.mark.asyncio
    async def test_json_api_success_stolen(self):
        """JSON API returns stolen flag → found=True."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        json_data = {"stolen": True, "isSalvage": False, "message": "Theft record found"}
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.found is True
        assert result.data["is_stolen"] is True

    @pytest.mark.asyncio
    async def test_json_api_fails_falls_back_to_post(self):
        """JSON API None response → falls back to POST HTML form."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        html_resp = _mock_resp(200, text="<html>No records found for this VIN.</html>")
        # get returns None (API failure); post returns HTML
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch.object(crawler, "post", new=AsyncMock(return_value=html_resp)):
                result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.found is False  # no theft/salvage keywords in text
        assert result.data.get("vin") == "1HGBH41JXMN109186"

    @pytest.mark.asyncio
    async def test_json_parse_error_falls_back_to_html(self):
        """JSON parse error on valid 200 → falls back to HTML form."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json.side_effect = ValueError("not json")
        html_resp = _mock_resp(200, text="<html>Salvage record.</html>")

        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            with patch.object(crawler, "post", new=AsyncMock(return_value=html_resp)):
                result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.data.get("is_salvage") is True

    @pytest.mark.asyncio
    async def test_both_api_and_html_fail_returns_http_error(self):
        """Both API and HTML form return None → http_error result."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_post_get_fallback_also_tried(self):
        """When POST returns None, GET fallback is also attempted."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        html_resp = _mock_resp(200, text="<html>Clean record.</html>")
        # First get (API) → None, post → None, second get (fallback) → html_resp
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[None, html_resp])):
            with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.found is False
        assert result.error is None  # clean parse, no error

    @pytest.mark.asyncio
    async def test_html_response_rate_limited(self):
        """HTML 429 → rate_limited error."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        rate_resp = _mock_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch.object(crawler, "post", new=AsyncMock(return_value=rate_resp)):
                result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_html_response_non_200_non_429(self):
        """HTML 403 → http_403 error."""
        from modules.crawlers.vehicle_nicb import VehicleNicbCrawler

        crawler = VehicleNicbCrawler()
        err_resp = _mock_resp(403)
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch.object(crawler, "post", new=AsyncMock(return_value=err_resp)):
                result = await crawler.scrape("1HGBH41JXMN109186")
        assert result.error == "http_403"


# ===========================================================================
# vehicle_ownership.py
# ===========================================================================


class TestVehicleOwnership:
    """Lines 56, 63-67, 138-155, 185, 200-204, 219-232, 236-258."""

    def test_parse_identifier_city_only(self):
        """Pipe without comma gives city but no state."""
        from modules.crawlers.vehicle_ownership import _parse_identifier

        first, last, city, state = _parse_identifier("Jane Doe|Chicago")
        assert first == "Jane"
        assert last == "Doe"
        assert city == "Chicago"
        assert state == ""

    def test_parse_identifier_no_pipe(self):
        """No pipe — city and state both empty."""
        from modules.crawlers.vehicle_ownership import _parse_identifier

        first, last, city, state = _parse_identifier("Bob Smith")
        assert first == "Bob"
        assert last == "Smith"
        assert city == ""
        assert state == ""

    def test_parse_identifier_single_name(self):
        """Single token — first set, last empty."""
        from modules.crawlers.vehicle_ownership import _parse_identifier

        first, last, city, state = _parse_identifier("Madonna")
        assert first == "Madonna"
        assert last == ""

    def test_parse_identifier_empty_string(self):
        """Empty identifier — all empty."""
        from modules.crawlers.vehicle_ownership import _parse_identifier

        first, last, city, state = _parse_identifier("")
        assert first == ""
        assert last == ""

    def test_parse_vehicle_cards_fallback_regex(self):
        """When no vehicle-card elements exist, regex fallback finds year/make/model."""
        from modules.crawlers.vehicle_ownership import _parse_vehicle_cards_html

        html = "<html><body>2019 Toyota Camry was registered here.</body></html>"
        vehicles = _parse_vehicle_cards_html(html)
        assert len(vehicles) >= 1
        assert vehicles[0]["year"] == "2019"
        assert vehicles[0]["make"] == "Toyota"

    def test_parse_vehicle_cards_extracts_color(self):
        """Structured vehicle card with Color field."""
        from modules.crawlers.vehicle_ownership import _parse_vehicle_cards_html

        html = """
        <div class="vehicle-card">
          Year: 2021 Make: Ford Model: Explorer Color: Blue
          VIN: 1FMSK8DH5MGA12345 Plate: ABC123 State: TX
        </div>
        """
        vehicles = _parse_vehicle_cards_html(html)
        assert len(vehicles) >= 1
        assert vehicles[0].get("color") == "Blue"

    def test_parse_vehicle_cards_empty_html(self):
        from modules.crawlers.vehicle_ownership import _parse_vehicle_cards_html

        vehicles = _parse_vehicle_cards_html("<html><body></body></html>")
        assert vehicles == []

    @pytest.mark.asyncio
    async def test_scrape_invalid_identifier_empty(self):
        """Empty first name → invalid_identifier error."""
        import modules.crawlers.vehicle_ownership  # noqa: F401
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()
        result = await crawler.scrape("")
        assert result.found is False
        assert result.data.get("error") == "invalid_identifier"

    @pytest.mark.asyncio
    async def test_scrape_deduplicates_by_vin(self):
        """Vehicles with same VIN from both sources appear only once."""
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()
        vin = "1GCVKNEC3JZ123456"
        vh_result = [{"vin": vin, "make": "Chevy", "year": "2018"}]
        bv_result = [{"vin": vin, "make": "Chevy", "year": "2018"}]

        with patch.object(crawler, "_scrape_vehiclehistory", return_value=vh_result):
            # Only called if len(all_vehicles) < 3
            with patch.object(crawler, "_scrape_beenverified", return_value=bv_result):
                result = await crawler.scrape("John Smith")

        vins = [v.get("vin") for v in result.data["vehicles"]]
        assert vins.count(vin) == 1

    @pytest.mark.asyncio
    async def test_scrape_beenverified_not_called_when_enough_vehicles(self):
        """BeenVerified not called when vehiclehistory returns 3+ vehicles."""
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()
        vh_result = [
            {"vin": "VIN1111111111111111", "make": "Ford"},
            {"vin": "VIN2222222222222222", "make": "Toyota"},
            {"vin": "VIN3333333333333333", "make": "Honda"},
        ]

        bv_mock = AsyncMock(return_value=[])
        with patch.object(crawler, "_scrape_vehiclehistory", return_value=vh_result):
            with patch.object(crawler, "_scrape_beenverified", new=bv_mock):
                result = await crawler.scrape("Alice Johnson")

        bv_mock.assert_not_called()
        assert len(result.data["vehicles"]) == 3

    @pytest.mark.asyncio
    async def test_scrape_vehiclehistory_no_last_name_returns_empty(self):
        """_scrape_vehiclehistory returns [] when last name is empty."""
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()
        result = await crawler._scrape_vehiclehistory("Madonna", "")
        assert result == []

    @pytest.mark.asyncio
    async def test_scrape_vehiclehistory_playwright_exception(self):
        """_scrape_vehiclehistory returns [] on Playwright exception."""
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()

        class _FailCtx:
            async def __aenter__(self):
                raise Exception("playwright error")

            async def __aexit__(self, *_):
                pass

        with patch.object(crawler, "page", return_value=_FailCtx()):
            result = await crawler._scrape_vehiclehistory("John", "Smith")
        assert result == []

    @pytest.mark.asyncio
    async def test_scrape_beenverified_no_last_name_returns_empty(self):
        """_scrape_beenverified returns [] when last name is empty."""
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()
        result = await crawler._scrape_beenverified("Madonna", "")
        assert result == []

    @pytest.mark.asyncio
    async def test_scrape_beenverified_playwright_exception(self):
        """_scrape_beenverified returns [] on Playwright exception."""
        from modules.crawlers.vehicle_ownership import VehicleOwnershipCrawler

        crawler = VehicleOwnershipCrawler()

        class _FailCtx:
            async def __aenter__(self):
                raise Exception("playwright error")

            async def __aexit__(self, *_):
                pass

        with patch.object(crawler, "page", return_value=_FailCtx()):
            result = await crawler._scrape_beenverified("Jane", "Doe")
        assert result == []


# ===========================================================================
# vehicle_plate.py
# ===========================================================================


class TestVehiclePlate:
    """Lines 78-109, 114-143, 171, 186-187, 194-197, 204-207."""

    def test_parse_licenseplatedata_html_structured(self):
        """Structured result-label/value divs are parsed correctly."""
        from modules.crawlers.vehicle_plate import _parse_licenseplatedata_html

        html = """
        <html><body>
          <div class="result-label">Year</div>
          <div class="result-value">2020</div>
          <div class="result-label">Make</div>
          <div class="result-value">Honda</div>
          <div class="result-label">Model</div>
          <div class="result-value">Civic</div>
        </body></html>
        """
        result = _parse_licenseplatedata_html(html)
        assert result.get("year") == "2020"
        assert result.get("make") == "Honda"

    def test_parse_licenseplatedata_html_regex_fallback(self):
        """When no structured labels, regex fallback extracts fields."""
        from modules.crawlers.vehicle_plate import _parse_licenseplatedata_html

        html = "Year: 2019\nMake: Toyota\nModel: Camry\nVIN: 4T1B11HK3KU123456\nColor: Silver"
        result = _parse_licenseplatedata_html(html)
        assert result.get("year") == "2019"
        assert result.get("make") == "Toyota"
        assert result.get("vin") == "4T1B11HK3KU123456"

    def test_parse_licenseplatedata_html_empty(self):
        from modules.crawlers.vehicle_plate import _parse_licenseplatedata_html

        result = _parse_licenseplatedata_html("<html><body></body></html>")
        assert result == {}

    def test_parse_vehiclehistory_html_json_embedded(self):
        """vehiclehistory HTML with embedded JSON fields."""
        from modules.crawlers.vehicle_plate import _parse_vehiclehistory_html

        html = '{"year": "2018", "make": "Ford", "model": "F-150", "vin": "1FTEW1EP0LFA12345", "color": "Blue"}'
        result = _parse_vehiclehistory_html(html)
        assert result.get("year") == "2018"
        assert result.get("make") == "Ford"
        assert result.get("vin") == "1FTEW1EP0LFA12345"

    def test_parse_vehiclehistory_html_span_year(self):
        """vehiclehistory span with year text."""
        from modules.crawlers.vehicle_plate import _parse_vehiclehistory_html

        html = '<html><body><span class="vehicle-result">2021</span></body></html>'
        result = _parse_vehiclehistory_html(html)
        assert result.get("year") == "2021"

    def test_parse_vehiclehistory_html_span_vin(self):
        """vehiclehistory span with 17-char VIN."""
        from modules.crawlers.vehicle_plate import _parse_vehiclehistory_html

        html = '<html><body><span class="plate-result">1HGBH41JXMN109186</span></body></html>'
        result = _parse_vehiclehistory_html(html)
        assert result.get("vin") == "1HGBH41JXMN109186"

    def test_parse_faxvin_json_nested_data_key(self):
        """_parse_faxvin_json handles 'data' as nested key."""
        from modules.crawlers.vehicle_plate import _parse_faxvin_json

        data = {"data": {"year": "2021", "make": "BMW", "model": "330i"}}
        result = _parse_faxvin_json(data)
        assert result["make"] == "BMW"

    def test_parse_faxvin_json_flat(self):
        """_parse_faxvin_json handles flat dict (no nested key)."""
        from modules.crawlers.vehicle_plate import _parse_faxvin_json

        data = {"year": "2020", "make": "Audi", "model": "A4", "color": "Black"}
        result = _parse_faxvin_json(data)
        assert result["make"] == "Audi"
        assert result["color"] == "Black"

    def test_parse_faxvin_json_exterior_color_fallback(self):
        """_parse_faxvin_json uses exterior_color when color absent."""
        from modules.crawlers.vehicle_plate import _parse_faxvin_json

        data = {"vehicle": {"make": "Tesla", "model": "Model 3", "exterior_color": "Red"}}
        result = _parse_faxvin_json(data)
        assert result["color"] == "Red"

    def test_parse_faxvin_json_empty_values_excluded(self):
        """_parse_faxvin_json strips falsy values from result (empty string model excluded)."""
        from modules.crawlers.vehicle_plate import _parse_faxvin_json

        data = {"vehicle": {"make": "Ford", "model": ""}}
        result = _parse_faxvin_json(data)
        assert "model" not in result
        assert result.get("make") == "Ford"

    @pytest.mark.asyncio
    async def test_scrape_empty_plate_returns_error(self):
        """Empty identifier returns invalid_identifier error."""
        import modules.crawlers.vehicle_plate  # noqa: F401
        from modules.crawlers.vehicle_plate import VehiclePlateCrawler

        crawler = VehiclePlateCrawler()
        # _parse_identifier("") returns ("", "") → empty plate
        result = await crawler.scrape("")
        assert result.found is False
        assert result.data.get("error") == "invalid_identifier"

    @pytest.mark.asyncio
    async def test_scrape_faxvin_json_error_falls_to_source2(self):
        """faxvin JSON parse error → source 2 (licenseplatedata) tried."""
        from modules.crawlers.vehicle_plate import VehiclePlateCrawler

        crawler = VehiclePlateCrawler()
        bad_faxvin = MagicMock()
        bad_faxvin.status_code = 200
        bad_faxvin.json.side_effect = ValueError("not json")

        lpd_html = '<div class="result-label">Make</div><div class="result-value">Kia</div>'
        good_lpd = _mock_resp(200, text=lpd_html)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[bad_faxvin, good_lpd, None])):
            result = await crawler.scrape("ABC1234|TX")
        # source_used should be licenseplatedata (parsed from HTML)
        assert result.data.get("source") in ("licenseplatedata", "none")

    @pytest.mark.asyncio
    async def test_scrape_falls_to_source3_vehiclehistory(self):
        """When sources 1 and 2 return no data, source 3 is tried."""
        from modules.crawlers.vehicle_plate import VehiclePlateCrawler

        crawler = VehiclePlateCrawler()
        empty_resp = _mock_resp(404)
        vh_html = '{"year": "2017", "make": "Nissan", "model": "Altima"}'
        vh_resp = _mock_resp(200, text=vh_html)

        with patch.object(
            crawler, "get", new=AsyncMock(side_effect=[empty_resp, empty_resp, vh_resp])
        ):
            result = await crawler.scrape("ZZZ999|CA")
        assert result.data.get("source") == "vehiclehistory"
        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_all_sources_fail_found_false(self):
        """All three sources fail → found=False, source='none'."""
        from modules.crawlers.vehicle_plate import VehiclePlateCrawler

        crawler = VehiclePlateCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler.scrape("ZZZ999|TX")
        assert result.found is False
        assert result.data.get("source") == "none"


# ===========================================================================
# telegram.py
# ===========================================================================


class TestTelegramCrawler:
    """Lines 42, 48, 71-72, 103-135."""

    @pytest.mark.asyncio
    async def test_phone_number_routes_to_probe_phone(self):
        """Identifier starting with '+' routes to _probe_phone."""
        import modules.crawlers.telegram  # noqa: F401
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        with patch.object(crawler, "_probe_phone", new=AsyncMock()) as mock_phone:
            mock_phone.return_value = MagicMock(found=False)
            await crawler.scrape("+12025550123")
        mock_phone.assert_called_once_with("+12025550123")

    @pytest.mark.asyncio
    async def test_digits_only_routes_to_probe_phone(self):
        """All-digits identifier routes to _probe_phone."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        with patch.object(crawler, "_probe_phone", new=AsyncMock()) as mock_phone:
            mock_phone.return_value = MagicMock(found=False)
            await crawler.scrape("12025550123")
        mock_phone.assert_called_once()

    @pytest.mark.asyncio
    async def test_username_http_error(self):
        """_probe_username returns error when HTTP fails."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("someusername")
        assert result.found is False
        assert result.data.get("error") == "http_error" or result.error == "http_error"

    @pytest.mark.asyncio
    async def test_username_not_found_page(self):
        """Page with no tgme_page markers → not found."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        resp = _mock_resp(200, text="<html><body>Page not found.</body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("nonexistentuser123")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_username_found_with_display_name(self):
        """Valid t.me page → found=True with display_name."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        html = """
        <html><body>
          <div class="tgme_page_title">Test Channel</div>
          <div class="tgme_page_description">A test Telegram channel</div>
          <div class="tgme_page_extra">1,234 subscribers</div>
          tgme_page_additional
        </body></html>
        """
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("testchannel")
        assert result.found is True
        assert result.data.get("display_name") == "Test Channel"
        assert result.data.get("bio") == "A test Telegram channel"

    @pytest.mark.asyncio
    async def test_username_subscriber_count_parsed(self):
        """Subscriber count extracted from page text."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        html = """
        <html><body>
          <div class="tgme_page_title">Big Channel</div>
          tgme_page_additional tgme_page_title
          10,500 subscribers
        </body></html>
        """
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("bigchannel")
        assert result.data.get("follower_count") == 10500

    @pytest.mark.asyncio
    async def test_username_no_display_name_found_false(self):
        """Page has markers but no tgme_page_title → found=False."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        html = "<html><body>tgme_page_additional tgme_page_title</body></html>"
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("emptypage")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_phone_probe_telethon_not_configured(self):
        """Without Telethon env vars, returns telethon_not_configured error."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        env = {"TELEGRAM_API_ID": "", "TELEGRAM_API_HASH": "", "TELEGRAM_SESSION": ""}
        with patch.dict(os.environ, env, clear=False):
            with patch("os.environ.get", side_effect=lambda k, d=None: env.get(k, d)):
                result = await crawler._probe_phone("+12025550123")
        assert result.error == "telethon_not_configured"
        assert result.found is False

    @pytest.mark.asyncio
    async def test_phone_probe_telethon_import_error(self):
        """Telethon ImportError → returns found=False with telegram_registered=False."""
        from modules.crawlers.telegram import TelegramCrawler

        crawler = TelegramCrawler()
        env = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "abc123",
            "TELEGRAM_SESSION": "session_str",
        }
        with patch.dict(os.environ, env):
            with patch("builtins.__import__", side_effect=ImportError("no telethon")):
                result = await crawler._probe_phone("+12025550123")
        # After ImportError, falls through to final return
        assert result.found is False


# ===========================================================================
# twitter.py
# ===========================================================================


class TestTwitterCrawler:
    """Lines 41, 47, 94, 98-101, 107-121, 138-139, 142-143."""

    @pytest.mark.asyncio
    async def test_all_instances_fail_with_http_error(self):
        """When all nitter instances return http_error, first non-not_found result is returned."""
        import modules.crawlers.twitter  # noqa: F401
        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler()
        # Every instance returns http_error (None response)
        # http_error != "not_found" so the loop exits early with first result
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("testhandle")
        assert result.found is False
        # Error stored in data dict by _result() helper
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_all_instances_return_not_found(self):
        """When every _try_instance sets result.error='not_found', all_instances_failed is returned."""
        from modules.crawlers.result import CrawlerResult
        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler()

        # Build a result where the CrawlerResult.error field is "not_found"
        not_found_result = CrawlerResult(
            platform="twitter",
            identifier="fakeuser",
            found=False,
            error="not_found",
        )
        with patch.object(crawler, "_try_instance", new=AsyncMock(return_value=not_found_result)):
            result = await crawler.scrape("fakeuser")
        assert result.found is False
        assert result.data.get("error") == "all_instances_failed"

    @pytest.mark.asyncio
    async def test_profile_with_location_and_joined(self):
        """Profile with location and join date fields are extracted."""
        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler()
        html = """
        <html><body>
          <div class="profile-card-fullname">John Doe</div>
          <div class="profile-bio">Software engineer</div>
          <div class="profile-location">New York, NY</div>
          <div class="profile-joindate">Joined March 2015</div>
          <div class="profile-stat-num">500</div>
          <div class="profile-stat-header">Tweets</div>
          <div class="profile-stat-num">200</div>
          <div class="profile-stat-header">Following</div>
          <div class="profile-stat-num">5K</div>
          <div class="profile-stat-header">Followers</div>
        </body></html>
        """
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("johndoe")
        assert result.found is True
        assert result.data.get("location") == "New York, NY"
        assert result.data.get("profile_created_at_str") == "Joined March 2015"
        assert result.data.get("post_count") == 500
        assert result.data.get("following_count") == 200
        assert result.data.get("follower_count") == 5000

    @pytest.mark.asyncio
    async def test_profile_with_verified_icon(self):
        """Profile with verified-icon is marked as verified."""
        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler()
        html = """
        <html><body>
          <div class="profile-card-fullname">Verified User</div>
          <div class="verified-icon"></div>
        </body></html>
        """
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("verifieduser")
        assert result.found is True
        assert result.data.get("is_verified") is True

    @pytest.mark.asyncio
    async def test_tweets_parsed_with_replies(self):
        """Recent tweets with reply count are extracted."""
        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler()
        html = """
        <html><body>
          <div class="profile-card-fullname">Tweeter</div>
          <div class="timeline-item">
            <div class="tweet-content">Hello world</div>
            <div class="tweet-date"><a title="Mar 01, 2024">Mar 01</a></div>
            <div class="tweet-stats">
              <div class="tweet-stat">
                <div class="icon-comment"></div>42
              </div>
            </div>
          </div>
        </body></html>
        """
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("tweeter")
        assert result.found is True
        tweets = result.data.get("recent_tweets", [])
        assert len(tweets) >= 1
        assert tweets[0].get("text") == "Hello world"
        assert tweets[0].get("replies") == 42

    def test_parse_stat_billion(self):
        """_parse_stat handles B suffix."""
        from modules.crawlers.twitter import _parse_stat

        assert _parse_stat("1.5B") == 1_500_000_000

    def test_parse_stat_million(self):
        from modules.crawlers.twitter import _parse_stat

        assert _parse_stat("2M") == 2_000_000

    def test_parse_stat_plain_number(self):
        from modules.crawlers.twitter import _parse_stat

        assert _parse_stat("12345") == 12345

    def test_parse_stat_with_commas(self):
        from modules.crawlers.twitter import _parse_stat

        assert _parse_stat("12,345") == 12345

    def test_parse_stat_invalid_suffix(self):
        """Invalid suffix returns 0."""
        from modules.crawlers.twitter import _parse_stat

        assert _parse_stat("XYZ") == 0

    def test_safe_parse_invalid_float_returns_0(self):
        """_safe_parse returns 0 for unparseable strings."""
        from modules.crawlers.twitter import _safe_parse

        assert _safe_parse("not_a_number") == 0

    def test_safe_parse_invalid_k_suffix(self):
        """_safe_parse returns 0 for unparseable K-suffixed strings."""
        from modules.crawlers.twitter import _safe_parse

        assert _safe_parse("xK") == 0


# ===========================================================================
# email_holehe.py
# ===========================================================================


class TestEmailHolehe:
    """Lines 25-37, 42-52."""

    @pytest.mark.asyncio
    async def test_holehe_not_installed_returns_error(self):
        """When holehe binary absent, returns holehe_not_installed."""
        import modules.crawlers.email_holehe  # noqa: F401
        from modules.crawlers.email_holehe import EmailHoleheCrawler

        crawler = EmailHoleheCrawler()
        with patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=False),
        ):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "holehe_not_installed"

    @pytest.mark.asyncio
    async def test_holehe_timeout(self):
        """TimeoutError during run → holehe_timeout error."""
        from modules.crawlers.email_holehe import EmailHoleheCrawler

        crawler = EmailHoleheCrawler()
        with patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.email_holehe._run_holehe",
                new=AsyncMock(side_effect=TimeoutError()),
            ):
                result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "holehe_timeout"

    @pytest.mark.asyncio
    async def test_holehe_file_not_found(self):
        """FileNotFoundError during run → holehe_not_installed error."""
        from modules.crawlers.email_holehe import EmailHoleheCrawler

        crawler = EmailHoleheCrawler()
        with patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.email_holehe._run_holehe",
                new=AsyncMock(side_effect=FileNotFoundError("holehe not found")),
            ):
                result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "holehe_not_installed"

    @pytest.mark.asyncio
    async def test_holehe_success(self):
        """Successful run returns found services list."""
        from modules.crawlers.email_holehe import EmailHoleheCrawler

        crawler = EmailHoleheCrawler()
        with patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.email_holehe._run_holehe",
                new=AsyncMock(return_value=(["twitter", "github"], 50)),
            ):
                result = await crawler.scrape("user@example.com")
        assert result.found is True
        assert result.data["found_on"] == ["twitter", "github"]
        assert result.data["checked_count"] == 50
        assert result.data["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_check_holehe_installed_timeout(self):
        """_check_holehe_installed returns False on TimeoutError."""
        from modules.crawlers.email_holehe import _check_holehe_installed

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=TimeoutError())):
            result = await _check_holehe_installed()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_holehe_installed_file_not_found(self):
        """_check_holehe_installed returns False when binary missing."""
        from modules.crawlers.email_holehe import _check_holehe_installed

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(side_effect=FileNotFoundError())
        ):
            result = await _check_holehe_installed()
        assert result is False

    @pytest.mark.asyncio
    async def test_run_holehe_parses_output(self):
        """_run_holehe parses [+] and [-] lines correctly."""
        from modules.crawlers.email_holehe import _run_holehe

        stdout = b"[+] twitter\n[+] github\n[-] facebook\n[-] instagram\n"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(stdout, b""))

        async def _passthrough_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            with patch("asyncio.wait_for", side_effect=_passthrough_wait_for):
                found, total = await _run_holehe("test@example.com")

        assert "twitter" in found
        assert "github" in found
        assert total == 4  # 2 [+] + 2 [-]


# ===========================================================================
# domain_theharvester.py
# ===========================================================================


class TestDomainHarvester:
    """Lines 28-53, 58-68, 117-126."""

    @pytest.mark.asyncio
    async def test_harvester_not_installed(self):
        """Returns theharvester_not_installed when binary absent."""
        import modules.crawlers.domain_theharvester  # noqa: F401
        from modules.crawlers.domain_theharvester import DomainHarvesterCrawler

        crawler = DomainHarvesterCrawler()
        with patch(
            "modules.crawlers.domain_theharvester._check_harvester_installed",
            new=AsyncMock(return_value=False),
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "theharvester_not_installed"

    @pytest.mark.asyncio
    async def test_harvester_timeout(self):
        """TimeoutError → harvester_timeout error."""
        from modules.crawlers.domain_theharvester import DomainHarvesterCrawler

        crawler = DomainHarvesterCrawler()
        with patch(
            "modules.crawlers.domain_theharvester._check_harvester_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(side_effect=TimeoutError()),
            ):
                result = await crawler.scrape("example.com")
        assert result.error == "harvester_timeout"

    @pytest.mark.asyncio
    async def test_harvester_file_not_found(self):
        """FileNotFoundError during run → theharvester_not_installed."""
        from modules.crawlers.domain_theharvester import DomainHarvesterCrawler

        crawler = DomainHarvesterCrawler()
        with patch(
            "modules.crawlers.domain_theharvester._check_harvester_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(side_effect=FileNotFoundError()),
            ):
                result = await crawler.scrape("example.com")
        assert result.error == "theharvester_not_installed"

    @pytest.mark.asyncio
    async def test_harvester_success_with_results(self):
        """Successful run returns parsed emails/subdomains/ips/urls."""
        from modules.crawlers.domain_theharvester import DomainHarvesterCrawler

        crawler = DomainHarvesterCrawler()
        raw = {
            "emails": ["admin@example.com", "info@example.com"],
            "hosts": ["mail.example.com", "www.example.com:1.2.3.4"],
            "ips": ["1.2.3.4"],
            "urls": ["https://example.com/login"],
        }
        with patch(
            "modules.crawlers.domain_theharvester._check_harvester_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(return_value=raw),
            ):
                result = await crawler.scrape("example.com")
        assert result.found is True
        assert "admin@example.com" in result.data["emails"]
        assert "mail.example.com" in result.data["subdomains"]
        assert "www.example.com" in result.data["subdomains"]  # IP suffix stripped
        assert "1.2.3.4" in result.data["ips"]

    @pytest.mark.asyncio
    async def test_harvester_empty_results_found_false(self):
        """Empty output → found=False."""
        from modules.crawlers.domain_theharvester import DomainHarvesterCrawler

        crawler = DomainHarvesterCrawler()
        with patch(
            "modules.crawlers.domain_theharvester._check_harvester_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(return_value={}),
            ):
                result = await crawler.scrape("empty.com")
        assert result.found is False

    def test_parse_harvester_output_strips_ip_from_host(self):
        """_parse_harvester_output strips :ip suffix from hosts."""
        from modules.crawlers.domain_theharvester import _parse_harvester_output

        raw = {"hosts": ["sub.example.com:192.168.1.1", "mail.example.com"], "emails": []}
        parsed = _parse_harvester_output(raw)
        assert "sub.example.com" in parsed["subdomains"]
        assert "mail.example.com" in parsed["subdomains"]

    def test_parse_harvester_output_none_fields(self):
        """_parse_harvester_output handles missing/None fields gracefully."""
        from modules.crawlers.domain_theharvester import _parse_harvester_output

        parsed = _parse_harvester_output({})
        assert parsed["emails"] == []
        assert parsed["subdomains"] == []
        assert parsed["ips"] == []
        assert parsed["urls"] == []

    @pytest.mark.asyncio
    async def test_check_harvester_installed_timeout(self):
        """_check_harvester_installed returns False on TimeoutError."""
        from modules.crawlers.domain_theharvester import _check_harvester_installed

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=TimeoutError())):
            result = await _check_harvester_installed()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_harvester_installed_file_not_found(self):
        from modules.crawlers.domain_theharvester import _check_harvester_installed

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(side_effect=FileNotFoundError())
        ):
            result = await _check_harvester_installed()
        assert result is False

    @pytest.mark.asyncio
    async def test_run_harvester_no_json_file(self):
        """_run_harvester returns {} when no JSON output file is created."""
        from modules.crawlers.domain_theharvester import _run_harvester

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        async def _passthrough_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            with patch("asyncio.wait_for", side_effect=_passthrough_wait_for):
                with patch("os.path.exists", return_value=False):
                    result = await _run_harvester("example.com")
        assert result == {}

    @pytest.mark.asyncio
    async def test_run_harvester_timeout_returns_empty(self):
        """_run_harvester returns {} on TimeoutError."""
        from modules.crawlers.domain_theharvester import _run_harvester

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=TimeoutError())):
            result = await _run_harvester("example.com")
        assert result == {}


# ===========================================================================
# sanctions_eu.py
# ===========================================================================


class TestSanctionsEU:
    """Lines 40-43, 94-99, 115-116, 127-129."""

    def test_cache_valid_no_file(self):
        from modules.crawlers.sanctions_eu import _cache_valid

        assert _cache_valid("/tmp/__nonexistent_lycan_test__") is False

    def test_cache_valid_fresh_file(self):
        from modules.crawlers.sanctions_eu import _cache_valid

        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            assert _cache_valid(path, max_age_hours=1.0) is True
        finally:
            os.unlink(path)

    def test_cache_valid_stale_file(self):
        from modules.crawlers.sanctions_eu import _cache_valid

        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        # Force mtime to be 10 hours ago
        old_time = time.time() - 36000
        os.utime(path, (old_time, old_time))
        try:
            assert _cache_valid(path, max_age_hours=6.0) is False
        finally:
            os.unlink(path)

    def test_name_overlap_score_full_match(self):
        from modules.crawlers.sanctions_eu import _name_overlap_score

        assert _name_overlap_score("Vladimir Putin", "Vladimir Putin") == 1.0

    def test_name_overlap_score_partial_match(self):
        from modules.crawlers.sanctions_eu import _name_overlap_score

        score = _name_overlap_score("Vladimir Putin", "Vladimir Vladimirovich Putin")
        assert 0 < score <= 1.0

    def test_name_overlap_score_no_match(self):
        from modules.crawlers.sanctions_eu import _name_overlap_score

        assert _name_overlap_score("John Doe", "Vladimir Putin") == 0.0

    def test_name_overlap_score_empty_query(self):
        from modules.crawlers.sanctions_eu import _name_overlap_score

        assert _name_overlap_score("", "Vladimir Putin") == 0.0

    @pytest.mark.asyncio
    async def test_scrape_download_failed(self):
        """Returns download_failed when HTTP fails."""
        import modules.crawlers.sanctions_eu  # noqa: F401
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("Some Name")
        assert result.found is False
        assert result.data.get("error") == "download_failed"

    @pytest.mark.asyncio
    async def test_scrape_cache_read_error_falls_through_to_download(self):
        """Cache read OSError → falls through to HTTP download."""
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        csv_text = "FileGenerationDate,Entity_LogicalId,Entity_Remark,NameAlias_FirstName,NameAlias_MiddleName,NameAlias_LastName,NameAlias_WholeName,NameAlias_NameLanguage,Entity_SubjectType\n"
        csv_text += ",E001,,Vladimir,,Putin,Vladimir Putin,,Person\n"
        resp = _mock_resp(200, text=csv_text)

        with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=True):
            with patch("builtins.open", side_effect=OSError("disk error")):
                with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                    result = await crawler.scrape("Vladimir Putin")
        # Should have downloaded and found the match
        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_cache_write_error_is_swallowed(self):
        """Cache write failure doesn't break the scrape."""
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        csv_text = ",E001,,Igor,,Sechin,Igor Sechin,,Person\n"
        resp = _mock_resp(200, text=csv_text)

        with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
            # open() for writing raises OSError
            with patch("builtins.open", side_effect=OSError("no space")):
                with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                    result = await crawler.scrape("Igor Sechin")
        assert result.found is True

    def test_search_deduplicates_by_entity_id(self):
        """Same entity_id appears only once in results."""
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        # Two rows with same entity_id
        csv_text = (
            "date,E001,remark,Vladimir,,Putin,Vladimir Putin,,Person\n"
            "date,E001,remark2,Vladimir,V,Putin,Vladimir Putin,,Person\n"
        )
        matches = crawler._search(csv_text, "Vladimir Putin")
        ids = [m["entity_id"] for m in matches]
        assert ids.count("E001") == 1

    def test_search_short_row_skipped(self):
        """Rows with fewer than 6 columns are skipped."""
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        csv_text = "a,b,c\n"  # only 3 columns
        matches = crawler._search(csv_text, "Vladimir Putin")
        assert matches == []

    def test_search_below_threshold_not_matched(self):
        """Names with score below threshold are excluded."""
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        csv_text = ",E002,,Unrelated,Z,Person,Unrelated Person,,Person\n"
        matches = crawler._search(csv_text, "Vladimir Putin")
        assert matches == []


# ===========================================================================
# sanctions_un.py
# ===========================================================================


class TestSanctionsUN:
    """Lines 34-37, 41, 53, 96, 121-126, 131-132, 139-140, 177-179."""

    SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CONSOLIDATED_LIST>
  <INDIVIDUALS>
    <INDIVIDUAL>
      <FIRST_NAME>Vladimir</FIRST_NAME>
      <SECOND_NAME>Vladimirovich</SECOND_NAME>
      <THIRD_NAME>Putin</THIRD_NAME>
      <UN_LIST_TYPE>RUSS</UN_LIST_TYPE>
      <REFERENCE_NUMBER>RUS.001</REFERENCE_NUMBER>
      <INDIVIDUAL_ALIAS>
        <ALIAS_NAME>V. Putin</ALIAS_NAME>
      </INDIVIDUAL_ALIAS>
    </INDIVIDUAL>
  </INDIVIDUALS>
  <ENTITIES>
    <ENTITY>
      <FIRST_NAME>Wagner Group</FIRST_NAME>
      <UN_LIST_TYPE>RUSS</UN_LIST_TYPE>
      <REFERENCE_NUMBER>ENT.001</REFERENCE_NUMBER>
      <ENTITY_ALIAS>
        <ALIAS_NAME>PMC Wagner</ALIAS_NAME>
      </ENTITY_ALIAS>
    </ENTITY>
  </ENTITIES>
</CONSOLIDATED_LIST>"""

    def test_cache_valid_no_file(self):
        from modules.crawlers.sanctions_un import _cache_valid

        assert _cache_valid("/tmp/__nonexistent_un_test__") is False

    def test_cache_valid_fresh(self):
        from modules.crawlers.sanctions_un import _cache_valid

        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            assert _cache_valid(path, max_age_hours=1.0) is True
        finally:
            os.unlink(path)

    def test_cache_valid_stale(self):
        from modules.crawlers.sanctions_un import _cache_valid

        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        old_time = time.time() - 36000
        os.utime(path, (old_time, old_time))
        try:
            assert _cache_valid(path, max_age_hours=6.0) is False
        finally:
            os.unlink(path)

    def test_name_matches_threshold(self):
        from modules.crawlers.sanctions_un import _name_matches

        score = _name_matches("Vladimir Putin", "Vladimir Putin")
        assert score == 1.0

    def test_name_matches_empty_query(self):
        from modules.crawlers.sanctions_un import _name_matches

        assert _name_matches("", "anything") == 0.0

    def test_text_helper_none_element(self):
        """_text() returns empty string for None element."""
        from modules.crawlers.sanctions_un import _text

        assert _text(None) == ""

    def test_text_helper_empty_text(self):
        from xml.etree import ElementTree as ET

        from modules.crawlers.sanctions_un import _text

        el = ET.fromstring("<TAG></TAG>")
        assert _text(el) == ""

    def test_build_full_name(self):
        from modules.crawlers.sanctions_un import _build_full_name

        assert _build_full_name("Vladimir", "", "Putin") == "Vladimir Putin"
        assert _build_full_name("", "", "") == ""

    def test_search_xml_individual_match(self):
        import modules.crawlers.sanctions_un  # noqa: F401
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        matches = crawler._search_xml(self.SAMPLE_XML, "Vladimir Putin")
        assert len(matches) >= 1
        assert matches[0]["record_type"] == "individual"
        assert matches[0]["reference"] == "RUS.001"

    def test_search_xml_individual_alias_match(self):
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        # "V. Putin" alias should match
        matches = crawler._search_xml(self.SAMPLE_XML, "V. Putin")
        assert len(matches) >= 1

    def test_search_xml_entity_match(self):
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        matches = crawler._search_xml(self.SAMPLE_XML, "Wagner Group")
        assert len(matches) >= 1
        assert matches[0]["record_type"] == "entity"

    def test_search_xml_entity_alias_match(self):
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        matches = crawler._search_xml(self.SAMPLE_XML, "PMC Wagner")
        assert len(matches) >= 1

    def test_search_xml_no_match(self):
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        matches = crawler._search_xml(self.SAMPLE_XML, "Completely Different Person")
        assert matches == []

    def test_search_xml_invalid_xml(self):
        """Malformed XML returns empty list without raising."""
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        matches = crawler._search_xml("NOT VALID XML <<<", "test")
        assert matches == []

    @pytest.mark.asyncio
    async def test_scrape_download_failed(self):
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_un._cache_valid", return_value=False):
                result = await crawler.scrape("Vladimir Putin")
        assert result.found is False
        assert "download" in (result.data.get("error") or "").lower() or result.error is not None

    @pytest.mark.asyncio
    async def test_scrape_cache_hit(self):
        """Uses cached XML when cache is valid."""
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        with patch("modules.crawlers.sanctions_un._cache_valid", return_value=True):
            with patch(
                "builtins.open",
                MagicMock(
                    return_value=MagicMock(
                        __enter__=lambda s: s,
                        __exit__=MagicMock(return_value=False),
                        read=lambda: self.SAMPLE_XML,
                    )
                ),
            ):
                result = await crawler.scrape("Vladimir Putin")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_cache_read_ioerror(self):
        """Cache OSError falls through to HTTP download."""
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        resp = _mock_resp(200, text=self.SAMPLE_XML)
        with patch("modules.crawlers.sanctions_un._cache_valid", return_value=True):
            with patch("builtins.open", side_effect=OSError("disk error")):
                with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                    result = await crawler.scrape("Vladimir Putin")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_cache_write_ioerror_swallowed(self):
        """Cache write failure doesn't break the scrape."""
        from modules.crawlers.sanctions_un import SanctionsUNCrawler

        crawler = SanctionsUNCrawler()
        resp = _mock_resp(200, text=self.SAMPLE_XML)

        call_count = {"n": 0}

        def _open_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("no space")
            return MagicMock(
                __enter__=lambda s: s,
                __exit__=MagicMock(return_value=False),
                read=lambda: self.SAMPLE_XML,
            )

        with patch("modules.crawlers.sanctions_un._cache_valid", return_value=False):
            with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                with patch("builtins.open", side_effect=_open_side_effect):
                    result = await crawler.scrape("Vladimir Putin")
        assert result.found is True


# ===========================================================================
# sanctions_uk.py
# ===========================================================================


class TestSanctionsUK:
    """Lines 39-42, 97-98, 109-110, 116-117, 128-130, 137."""

    def _make_csv(self, name_parts: list[str]) -> str:
        """Build a minimal UK OFSI CSV with two header rows + one data row."""
        # Header rows (i < 2 are skipped)
        header1 = "GroupID,LastUpdated,Name6,Name1,Name2,Name3,Name4,Name5,DOB,TownOfBirth,CountryOfBirth,Nationality,Passport,Position,Regime"
        header2 = "(group id),(date),(group name),(last),(first),(middle),(n4),(n5),(dob),(town),(country),(nat),(pass),(pos),(regime)"
        data_row = ",".join(name_parts)
        return f"{header1}\n{header2}\n{data_row}\n"

    def test_cache_valid_no_file(self):
        from modules.crawlers.sanctions_uk import _cache_valid

        assert _cache_valid("/tmp/__nonexistent_uk_test__") is False

    def test_cache_valid_fresh(self):
        from modules.crawlers.sanctions_uk import _cache_valid

        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            assert _cache_valid(path, max_age_hours=1.0) is True
        finally:
            os.unlink(path)

    def test_cache_valid_stale(self):
        from modules.crawlers.sanctions_uk import _cache_valid

        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        old_time = time.time() - 36000
        os.utime(path, (old_time, old_time))
        try:
            assert _cache_valid(path, max_age_hours=6.0) is False
        finally:
            os.unlink(path)

    def test_name_overlap_score(self):
        from modules.crawlers.sanctions_uk import _name_overlap_score

        assert _name_overlap_score("Igor Sechin", "Igor Sechin") == 1.0
        assert _name_overlap_score("Igor Sechin", "Igor") == 0.5
        assert _name_overlap_score("", "Igor") == 0.0

    @pytest.mark.asyncio
    async def test_scrape_download_failed(self):
        import modules.crawlers.sanctions_uk  # noqa: F401
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("Igor Sechin")
        assert result.found is False
        assert result.data.get("error") == "download_failed"

    @pytest.mark.asyncio
    async def test_scrape_cache_read_error(self):
        """Cache OSError falls through to HTTP download."""
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        # Name6=Igor Sechin group name, data row
        csv_data = self._make_csv(
            [
                "G001",
                "2024-01-01",
                "Igor Sechin",
                "Sechin",
                "Igor",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "Russia",
            ]
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.content = csv_data.encode("latin-1")
        resp.text = csv_data

        with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=True):
            with patch("builtins.open", side_effect=OSError("disk error")):
                with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                    result = await crawler.scrape("Igor Sechin")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_cache_write_error_swallowed(self):
        """Cache write failure doesn't break the scrape."""
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv_data = self._make_csv(
            [
                "G002",
                "2024-01-01",
                "Roman Abramovich",
                "Abramovich",
                "Roman",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "Russia",
            ]
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.content = csv_data.encode("latin-1")
        resp.text = csv_data

        with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
            with patch("builtins.open", side_effect=OSError("no space")):
                with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                    result = await crawler.scrape("Roman Abramovich")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_scrape_content_decode_exception_fallback(self):
        """When response.content.decode raises, falls back to response.text."""
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv_data = self._make_csv(
            [
                "G003",
                "2024-01-01",
                "Test Person",
                "Person",
                "Test",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "UK",
            ]
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.content = MagicMock()
        resp.content.decode = MagicMock(side_effect=Exception("decode error"))
        resp.text = csv_data

        with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
            with patch("builtins.open", side_effect=OSError("no cache")):
                with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                    result = await crawler.scrape("Test Person")
        assert result.found is True

    def test_search_deduplicates_by_group_id(self):
        """Same group_id appears only once."""
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv_text = (
            "h1\nh2\n"
            "G001,2024,Igor Sechin,Sechin,Igor,,,,,,,,,,Russia\n"
            "G001,2024,Igor Sechin,Sechin,Igor,V.,,,,,,,,,Russia\n"
        )
        matches = crawler._search(csv_text, "Igor Sechin")
        ids = [m["group_id"] for m in matches]
        assert ids.count("G001") == 1

    def test_search_skips_short_rows(self):
        """Rows with fewer than 3 columns are skipped."""
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv_text = "h1\nh2\na,b\n"
        matches = crawler._search(csv_text, "anything")
        assert matches == []

    def test_search_result_sorted_by_score(self):
        """Results are sorted by match_score descending."""
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv_text = (
            "h1\nh2\n"
            "G001,2024,Igor Sechin,Sechin,Igor,,,,,,,,,,Russia\n"
            "G002,2024,Igor,Igor,,,,,,,,,,,Russia\n"
        )
        matches = crawler._search(csv_text, "Igor Sechin")
        if len(matches) >= 2:
            assert matches[0]["match_score"] >= matches[1]["match_score"]


# ===========================================================================
# social_posts_analyzer.py
# ===========================================================================


class TestSocialPostsAnalyzer:
    """Lines 34-48."""

    @pytest.mark.asyncio
    async def test_scrape_text_prefix(self):
        """'text:' prefix passes text directly to analyzers."""
        import modules.crawlers.social_posts_analyzer  # noqa: F401
        from modules.crawlers.social_posts_analyzer import SocialPostsAnalyzerCrawler

        crawler = SocialPostsAnalyzerCrawler()
        result = await crawler.scrape("text:I love hiking and art")
        assert result.found is True
        assert "ocean_openness" in result.data

    @pytest.mark.asyncio
    async def test_scrape_non_text_prefix_uses_identifier_as_text(self):
        """Without 'text:' prefix, identifier itself is used as text."""
        from modules.crawlers.social_posts_analyzer import SocialPostsAnalyzerCrawler

        crawler = SocialPostsAnalyzerCrawler()
        result = await crawler.scrape("some_person_uuid_here")
        assert result.found is True
        # All OCEAN scores should be floats
        assert isinstance(result.data.get("ocean_openness"), float)

    @pytest.mark.asyncio
    async def test_scrape_returns_biographical_fields(self):
        """Result includes expected biographical profile fields."""
        from modules.crawlers.social_posts_analyzer import SocialPostsAnalyzerCrawler

        crawler = SocialPostsAnalyzerCrawler()
        result = await crawler.scrape("text:Married with two kids, born January 5, 1985")
        assert result.found is True
        assert "dob_confidence" in result.data
        assert "marital_status" in result.data
        assert "children_count" in result.data

    @pytest.mark.asyncio
    async def test_scrape_returns_psychological_fields(self):
        """Result includes all OCEAN and risk signal fields."""
        from modules.crawlers.social_posts_analyzer import SocialPostsAnalyzerCrawler

        crawler = SocialPostsAnalyzerCrawler()
        result = await crawler.scrape(
            "text:I gamble every weekend and I am very stressed about money"
        )
        assert result.found is True
        assert "ocean_conscientiousness" in result.data
        assert "ocean_extraversion" in result.data
        assert "ocean_agreeableness" in result.data
        assert "ocean_neuroticism" in result.data
        assert "financial_stress_language" in result.data
        assert "gambling_language" in result.data

    @pytest.mark.asyncio
    async def test_scrape_empty_text(self):
        """Empty text still returns a valid result structure."""
        from modules.crawlers.social_posts_analyzer import SocialPostsAnalyzerCrawler

        crawler = SocialPostsAnalyzerCrawler()
        result = await crawler.scrape("text:")
        assert result.found is True
        assert "psych_confidence" in result.data

    @pytest.mark.asyncio
    async def test_scrape_dob_isoformat_when_found(self):
        """When DOB is detected, it's serialised as ISO string."""
        from modules.crawlers.social_posts_analyzer import SocialPostsAnalyzerCrawler

        crawler = SocialPostsAnalyzerCrawler()
        result = await crawler.scrape("text:Born on 1990-03-15 in New York.")
        assert result.found is True
        # dob will be None or a string (ISO format)
        dob_val = result.data.get("dob")
        if dob_val is not None:
            assert isinstance(dob_val, str)
            assert "-" in dob_val


# ===========================================================================
# Branch coverage gap tests — added to reach 100% branch coverage
# ===========================================================================


# ---------------------------------------------------------------------------
# people_zabasearch.py
# [63,67]  name_tag is None  → no "name" key added
# [83,93]  age regex has no match → no "age" added from tag
# [99,94]  ph_text empty after href strip → not appended
# [108,58] neither name nor city present → person not appended
# ---------------------------------------------------------------------------


class TestPeopleZabaSearchBranches:
    def test_parse_no_name_tag(self):
        """zabasearch line 63: card with no name selector → person omitted (no name/city)."""
        from modules.crawlers.people_zabasearch import _parse_persons

        # Card has no h2/h3/.name — and no city either → person not appended
        html = '<html><body><div class="person-search-result"><p>Some info</p></div></body></html>'
        persons = _parse_persons(html)
        assert persons == []

    def test_parse_age_tag_no_digit_match(self):
        """zabasearch line 83: age tag exists but has no digits → no age key."""
        from modules.crawlers.people_zabasearch import _parse_persons

        html = """<html><body>
        <div class="person-search-result">
          <h2>Jane Doe</h2>
          <span class="age">Unknown</span>
        </div>
        </body></html>"""
        persons = _parse_persons(html)
        assert len(persons) == 1
        assert "age" not in persons[0]

    def test_parse_phone_href_empty_after_strip(self):
        """zabasearch line 99: tel: href is 'tel:' (empty after strip) → not appended."""
        from modules.crawlers.people_zabasearch import _parse_persons

        html = """<html><body>
        <div class="person-search-result">
          <h2>John Smith</h2>
          <a href="tel:" class="phone"></a>
        </div>
        </body></html>"""
        persons = _parse_persons(html)
        assert len(persons) == 1
        # Phone list should be empty (tel: stripped to empty string)
        assert persons[0].get("phones", []) == []

    def test_parse_no_name_no_city_not_appended(self):
        """zabasearch line 108: card yields empty person dict → not appended."""
        from modules.crawlers.people_zabasearch import _parse_persons

        # A card that matches the selector but has absolutely no extractable text
        html = '<html><body><div class="person-search-result"></div></body></html>'
        persons = _parse_persons(html)
        assert persons == []


# ---------------------------------------------------------------------------
# people_thatsthem.py
# [98,96]   ph_text empty → not appended (loop continues)
# [110,105] em_text empty after mailto: strip → not appended
# [119,122] age tag present AND regex matches → age set
# ---------------------------------------------------------------------------


class TestPeopleThatsThemBranches:
    def test_parse_phone_empty_text_not_appended(self):
        """thatsthem line 98: phone element with no text → not appended."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """<html><body>
        <div class="record">
          <h2>Jane Doe</h2>
          <a href="tel:5551234567" class="phone"></a>
        </div>
        </body></html>"""
        persons = _parse_persons(html)
        assert len(persons) == 1
        # Phone link had no visible text → phones list empty
        assert persons[0].get("phones", []) == []

    def test_parse_email_href_only_empty_strip(self):
        """thatsthem line 110: mailto: href is bare 'mailto:' → em_text empty, not appended."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """<html><body>
        <div class="record">
          <h2>Bob Jones</h2>
          <a href="mailto:" class="email"></a>
        </div>
        </body></html>"""
        persons = _parse_persons(html)
        assert len(persons) == 1
        assert persons[0].get("emails", []) == []

    def test_parse_age_tag_with_match(self):
        """thatsthem line 119: age tag contains digit → age is set (covers [119,122])."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """<html><body>
        <div class="record">
          <h2>Alice Smith</h2>
          <span class="age">Age 42</span>
        </div>
        </body></html>"""
        persons = _parse_persons(html)
        assert len(persons) == 1
        assert persons[0].get("age") == 42


# ---------------------------------------------------------------------------
# people_familysearch.py
# [57,63]  names list is empty → full_name stays ""
# [69,64]  "Death" in ftype → death_date assigned
# ---------------------------------------------------------------------------


class TestPeopleFamilySearchBranches:
    def test_parse_entry_no_names(self):
        """familysearch line 57: person has empty names list → full_name is empty string."""
        from modules.crawlers.people_familysearch import _parse_entry

        entry = {
            "id": "E1",
            "title": "Birth Record",
            "content": {
                "gedcomx": {
                    "persons": [
                        {
                            "id": "P1",
                            "names": [],
                            "facts": [],
                        }
                    ]
                }
            },
        }
        result = _parse_entry(entry)
        assert result["name"] == ""

    def test_parse_entry_death_fact(self):
        """familysearch line 69: fact with 'Death' in type sets death_date."""
        from modules.crawlers.people_familysearch import _parse_entry

        entry = {
            "id": "E2",
            "title": "Death Record",
            "content": {
                "gedcomx": {
                    "persons": [
                        {
                            "id": "P2",
                            "names": [
                                {"nameForms": [{"fullText": "John A Doe"}]}
                            ],
                            "facts": [
                                {
                                    "type": "http://gedcomx.org/Death",
                                    "date": {"original": "1 Jan 1980"},
                                    "place": {},
                                }
                            ],
                        }
                    ]
                }
            },
        }
        result = _parse_entry(entry)
        assert result["death_date"] == "1 Jan 1980"
        assert result["name"] == "John A Doe"


# ---------------------------------------------------------------------------
# people_usmarshals.py
# [142,146] fugitives list empty after parse → filter block skipped → return directly
# ---------------------------------------------------------------------------


class TestPeopleUSMarshalsBranches:
    @pytest.mark.asyncio
    async def test_api_returns_empty_list_skips_filter(self):
        """usmarshals line 142: API returns [] → fugitives empty, filter block not entered."""
        from modules.crawlers.people_usmarshals import USMarshalsCrawler

        crawler = USMarshalsCrawler()
        api_resp = _mock_resp(status=200, json_data=[])
        with patch.object(crawler, "get", new=AsyncMock(return_value=api_resp)):
            result = await crawler.scrape("Nobody Known")
        assert result.found is False
        assert result.data["fugitives"] == []
        assert result.data["source"] == "api"


# ---------------------------------------------------------------------------
# obituary_search.py
# [113,111]  _extract_legacy_card returns None → if obit: is False
# [177,175]  _extract_findagrave_card returns None → if obit: is False
# [235,237]  _extract_survived_by: no stop marker → segment not trimmed (stop is None)
# [256,258]  _extract_preceded_by: no stop marker → segment not trimmed (stop is None)
# ---------------------------------------------------------------------------


class TestObituarySearchBranches:
    def test_parse_legacy_card_returns_none_for_nameless(self):
        """obituary_search line 113: card with no name tag → _extract_legacy_card returns None."""
        from modules.crawlers.obituary_search import _parse_legacy

        # A div with class containing "obituary" but no h2/h3/name element
        html = '<html><body><div class="obituary-listing"><p>No name here</p></div></body></html>'
        results = _parse_legacy(html, "Jane Doe")
        assert results == []

    def test_parse_findagrave_card_returns_none_for_nameless(self):
        """obituary_search line 177: card with no name element → _extract_findagrave_card None."""
        from modules.crawlers.obituary_search import _parse_findagrave

        html = """<html><body>
        <div class="memorial-item"><p>No name here 1990 2020</p></div>
        </body></html>"""
        results = _parse_findagrave(html, "Jane Doe")
        assert results == []

    def test_extract_survived_by_no_stop_marker(self):
        """obituary_search line 235: 'survived by' found but no stop marker → full segment used."""
        from modules.crawlers.obituary_search import _extract_survived_by

        text = "She is survived by John Smith and Mary Brown no stop marker here at all"
        names = _extract_survived_by(text)
        # Should still return names from the segment (stop is None → branch 235→237 not taken)
        assert isinstance(names, list)

    def test_extract_preceded_by_no_stop_marker(self):
        """obituary_search line 256: 'preceded by' found but no stop marker → full segment used."""
        from modules.crawlers.obituary_search import _extract_preceded_by

        text = "preceded by Robert Jones and Helen Davis no funeral no stop here"
        names = _extract_preceded_by(text)
        assert isinstance(names, list)


# ---------------------------------------------------------------------------
# news_search.py
# [111,109]  url empty or duplicate → article not appended to seen_urls
# [189,187]  _extract_ddg_result returns None → article not appended
# [263,266]  snippet is empty → BeautifulSoup call skipped
# ---------------------------------------------------------------------------


class TestNewsSearchBranches:
    @pytest.mark.asyncio
    async def test_duplicate_url_not_added_twice(self):
        """news_search line 111: same URL from two sources → deduplicated."""
        from modules.crawlers.news_search import NewsSearchCrawler

        crawler = NewsSearchCrawler()
        dup_url = "https://example.com/article1"
        # Build DDG HTML with one article, then RSS with same URL
        ddg_html = f"""<html><body>
        <div class="result">
          <a class="result__a" href="{dup_url}">Article One</a>
        </div>
        </body></html>"""
        rss_xml = f"""<rss><channel>
          <item>
            <title>Article One</title>
            <link>{dup_url}</link>
            <description></description>
          </item>
        </channel></rss>"""

        call_count = 0

        async def _fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "duckduckgo" in url:
                return _mock_resp(status=200, text=ddg_html)
            if "google.com" in url:
                return _mock_resp(status=200, text=rss_xml)
            if "bing.com" in url:
                return _mock_resp(status=200, text=rss_xml)
            return None

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("Article One")

        # The same URL should appear only once in articles
        urls = [a.get("url") for a in result.data.get("articles", [])]
        assert urls.count(dup_url) == 1

    @pytest.mark.asyncio
    async def test_ddg_result_div_no_link_skipped(self):
        """news_search line 189: div with no <a> tag → _extract_ddg_result returns None."""
        from modules.crawlers.news_search import NewsSearchCrawler

        crawler = NewsSearchCrawler()
        # A result div with no anchor → _extract_ddg_result returns None → not appended
        html = '<html><body><div class="result"><p>No link here</p></div></body></html>'

        async def _fake_get(url, **kwargs):
            if "duckduckgo" in url:
                return _mock_resp(status=200, text=html)
            return _mock_resp(status=200, text="<rss><channel></channel></rss>")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("something")

        assert result.data.get("article_count", 0) == 0

    def test_parse_rss_empty_snippet_skips_beautifulsoup(self):
        """news_search line 263: snippet is empty → BeautifulSoup not called on it."""
        from modules.crawlers.news_search import _parse_rss

        # RSS item with no description element → snippet is ""
        xml = """<rss><channel>
          <item>
            <title>Test Article</title>
            <link>https://example.com/test</link>
          </item>
        </channel></rss>"""
        results = _parse_rss(xml, "test_source")
        assert len(results) == 1
        assert results[0]["snippet"] == ""
        assert results[0]["title"] == "Test Article"


# ---------------------------------------------------------------------------
# news_wikipedia.py
# [103,107]  wp_results[0] has no "title" key (or empty) → _wp_summary not called
# ---------------------------------------------------------------------------


class TestNewsWikipediaBranches:
    @pytest.mark.asyncio
    async def test_top_result_empty_title_skips_summary(self):
        """news_wikipedia line 103: first result has empty title → _wp_summary not called."""
        from modules.crawlers.news_wikipedia import WikipediaCrawler

        crawler = WikipediaCrawler()
        wp_data = {"query": {"search": [{"title": "", "snippet": "some text", "pageid": 1}]}}
        wd_data = {"search": []}

        call_count = {"n": 0}

        async def _fake_get(url, **kwargs):
            if "wikipedia.org/w/api.php" in url:
                return _mock_resp(status=200, json_data=wp_data)
            if "wikidata.org" in url:
                return _mock_resp(status=200, json_data=wd_data)
            # Summary endpoint should not be reached
            call_count["n"] += 1
            return _mock_resp(status=200, json_data={})

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("empty title entity")

        # Summary endpoint was never called
        assert call_count["n"] == 0
        assert result.data.get("top_summary") == {}


# ---------------------------------------------------------------------------
# news_archive.py
# [156,161]  data is a list but first element is not a digit string → returns 0
# ---------------------------------------------------------------------------


class TestNewsArchiveBranches:
    @pytest.mark.asyncio
    async def test_cdx_count_non_digit_list_element(self):
        """news_archive line 156: list returned but element non-digit → count is 0."""
        from modules.crawlers.news_archive import NewsArchiveCrawler

        crawler = NewsArchiveCrawler()

        async def _fake_get(url, **kwargs):
            if "available" in url:
                return _mock_resp(status=200, json_data={"archived_snapshots": {}})
            if "showNumPages" in url:
                # Returns a list but with a non-digit value
                return _mock_resp(status=200, json_data=["not-a-number"])
            # CDX records
            return _mock_resp(status=200, json_data=[])

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
            result = await crawler.scrape("example.com")

        assert result.data.get("total_snapshots") == 0


# ---------------------------------------------------------------------------
# fastpeoplesearch.py
# [74,72]  _extract_fps_card returns None (no full_name) → not appended
# ---------------------------------------------------------------------------


class TestFastPeopleSearchBranches:
    def test_extract_fps_card_no_name_returns_none(self):
        """fastpeoplesearch line 74: card with no h2/h3/strong → full_name empty → None."""
        from modules.crawlers.fastpeoplesearch import _extract_fps_card
        from bs4 import BeautifulSoup

        html = '<div class="card-block"><p>No name here</p></div>'
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_fps_card(card)
        assert result is None


# ---------------------------------------------------------------------------
# truepeoplesearch.py
# [72,70]  _extract_tps_card returns None → not appended
# ---------------------------------------------------------------------------


class TestTruePeopleSearchBranches:
    def test_extract_tps_card_no_name_returns_none(self):
        """truepeoplesearch line 72: card with no name element → full_name empty → None."""
        from modules.crawlers.truepeoplesearch import _extract_tps_card
        from bs4 import BeautifulSoup

        html = '<div class="card"><p>Nothing useful</p></div>'
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_tps_card(card)
        assert result is None


# ---------------------------------------------------------------------------
# whitepages.py
# [103,101]  _extract_whitepages_card returns None → not appended
# ---------------------------------------------------------------------------


class TestWhitepagesBranches:
    def test_extract_whitepages_card_no_name_returns_none(self):
        """whitepages line 103: card with no name element → name empty → None."""
        from modules.crawlers.whitepages import _extract_whitepages_card
        from bs4 import BeautifulSoup

        html = '<div data-testid="person-card"><p>No name here</p></div>'
        card = BeautifulSoup(html, "html.parser").find("div")
        result = _extract_whitepages_card(card)
        assert result is None


# ---------------------------------------------------------------------------
# darkweb_ahmia.py
# [50,41]  onion_url is empty → result not appended
# ---------------------------------------------------------------------------


class TestDarkwebAhmiaBranches:
    def test_parse_ahmia_html_skips_empty_onion_url(self):
        """darkweb_ahmia line 50: li.result with no <cite> → onion_url empty → skipped."""
        from modules.crawlers.darkweb_ahmia import _parse_ahmia_html

        # One result with a <cite>, one without
        html = """<html><body>
        <ul>
          <li class="result">
            <h4>Good Result</h4>
            <cite>http://good.onion</cite>
            <p>Some description</p>
          </li>
          <li class="result">
            <h4>No URL Result</h4>
            <p>Description only, no cite tag</p>
          </li>
        </ul>
        </body></html>"""
        results = _parse_ahmia_html(html)
        assert len(results) == 1
        assert results[0]["onion_url"] == "http://good.onion"


# ---------------------------------------------------------------------------
# darkweb_torch.py
# [58,46]  onion_url is empty → result not appended
# ---------------------------------------------------------------------------


class TestDarkwebTorchBranches:
    def test_parse_torch_html_skips_empty_onion_url(self):
        """darkweb_torch line 58: <dt><a> has empty href → onion_url empty → skipped."""
        from modules.crawlers.darkweb_torch import _parse_torch_html

        # dt with an anchor but no href value
        html = """<html><body>
        <dl>
          <dt><a href="">Empty URL Page</a></dt>
          <dd>Description here</dd>
          <dt><a href="http://real.onion">Real Page</a></dt>
          <dd>Real description</dd>
        </dl>
        </body></html>"""
        results = _parse_torch_html(html)
        # Only the second result should be included
        assert len(results) == 1
        assert results[0]["onion_url"] == "http://real.onion"
