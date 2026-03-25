"""
test_email_wave4.py — Branch-coverage gap tests (wave 4).

Crawlers covered:
  email_dehashed  — lines 25-27, 44-48, 51-155
  email_socialscan — lines 34-70

Each test targets specific uncovered lines identified in the coverage report.
All external I/O is mocked; no real network calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# email_dehashed.py
# Lines: 25-27 (_make_auth_header), 44-48 (_credentials), 51-155 (scrape)
# ===========================================================================


class TestDeHashedMakeAuthHeader:
    """Lines 25-27: standalone helper _make_auth_header."""

    def test_basic_encoding(self):
        import base64
        from modules.crawlers.email_dehashed import _make_auth_header

        result = _make_auth_header("user@example.com", "mysecret")
        expected = base64.b64encode(b"user@example.com:mysecret").decode()
        assert result == f"Basic {expected}"

    def test_special_characters_in_key(self):
        import base64
        from modules.crawlers.email_dehashed import _make_auth_header

        result = _make_auth_header("a@b.com", "k3y!@#$%")
        expected = base64.b64encode(b"a@b.com:k3y!@#$%").decode()
        assert result == f"Basic {expected}"


class TestDeHashedCredentials:
    """Lines 44-48: _credentials() reads from environment."""

    def _make(self):
        from modules.crawlers.email_dehashed import DeHashedCrawler
        return DeHashedCrawler()

    def test_credentials_both_set(self):
        crawler = self._make()
        with patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "key123"}):
            result = crawler._credentials()
        assert result == ("e@x.com", "key123")

    def test_credentials_missing_email(self):
        crawler = self._make()
        with patch.dict("os.environ", {}, clear=True):
            result = crawler._credentials()
        assert result is None

    def test_credentials_missing_api_key(self):
        crawler = self._make()
        with patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com"}, clear=True):
            result = crawler._credentials()
        assert result is None

    def test_credentials_missing_both(self):
        crawler = self._make()
        with patch.dict("os.environ", {}, clear=True):
            result = crawler._credentials()
        assert result is None


class TestDeHashedScrape:
    """Lines 51-155: scrape() — all branches."""

    def _make(self):
        from modules.crawlers.email_dehashed import DeHashedCrawler
        return DeHashedCrawler()

    # Line 51-59: missing credentials → found=False, error set
    @pytest.mark.asyncio
    async def test_scrape_no_credentials(self):
        crawler = self._make()
        with patch.dict("os.environ", {}, clear=True):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "DEHASHED_EMAIL or DEHASHED_API_KEY not set"

    # Line 72-81: self.get() raises an exception
    @pytest.mark.asyncio
    async def test_scrape_get_raises_exception(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(side_effect=RuntimeError("network error"))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "network error"

    # Line 83-90: response is None
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "no_response"

    # Lines 92-99: 401 Unauthorized
    @pytest.mark.asyncio
    async def test_scrape_401_invalid_credentials(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(401))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "invalid_credentials"

    # Lines 101-108: 400 Bad Request
    @pytest.mark.asyncio
    async def test_scrape_400_bad_request(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(400))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "bad_request"

    # Lines 110-117: 429 Rate Limited
    @pytest.mark.asyncio
    async def test_scrape_429_rate_limited(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    # Lines 119-126: other non-200 status (e.g. 503)
    @pytest.mark.asyncio
    async def test_scrape_non200_other(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "http_503"

    # Lines 128-137: response.json() raises → invalid_json
    @pytest.mark.asyncio
    async def test_scrape_invalid_json(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is False
        assert result.error == "invalid_json"

    # Lines 139-162: 200 with empty entries list → found=False
    @pytest.mark.asyncio
    async def test_scrape_200_empty_entries(self):
        crawler = self._make()
        json_data = {"total": 0, "took": 5, "entries": []}
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))),
        ):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["records"] == []
        assert result.data["total"] == 0

    # Lines 139-162: 200 with entries → found=True, records populated
    @pytest.mark.asyncio
    async def test_scrape_200_with_entries(self):
        crawler = self._make()
        json_data = {
            "total": 2,
            "took": 10,
            "entries": [
                {
                    "id": "abc123",
                    "email": "victim@example.com",
                    "username": "victim",
                    "name": "John Doe",
                    "ip_address": "1.2.3.4",
                    "phone": "5550001234",
                    "database_name": "BreachDB",
                    "hashed_password": "abc:hash",
                },
                {
                    "id": "def456",
                    "email": "victim@example.com",
                    "username": None,
                    "name": None,
                    "ip_address": None,
                    "phone": None,
                    "database_name": "OtherDB",
                    "hashed_password": None,
                },
            ],
        }
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))),
        ):
            result = await crawler.scrape("victim@example.com")
        assert result.found is True
        assert len(result.data["records"]) == 2
        assert result.data["records"][0]["id"] == "abc123"
        assert result.data["records"][0]["database_name"] == "BreachDB"
        assert result.data["records"][1]["id"] == "def456"
        assert result.data["total"] == 2

    # Lines 139: entries key absent → treated as empty
    @pytest.mark.asyncio
    async def test_scrape_200_no_entries_key(self):
        crawler = self._make()
        json_data = {"total": 0, "took": 1}
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))),
        ):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["records"] == []

    # entries=None fallback (or [] fallback)
    @pytest.mark.asyncio
    async def test_scrape_200_entries_none(self):
        crawler = self._make()
        json_data = {"total": 0, "entries": None}
        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))),
        ):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["records"] == []

    # Verify URL construction includes stripped identifier
    @pytest.mark.asyncio
    async def test_scrape_url_uses_stripped_identifier(self):
        crawler = self._make()
        json_data = {"total": 0, "entries": []}
        captured_urls = []

        async def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return _mock_resp(200, json_data=json_data)

        with (
            patch.dict("os.environ", {"DEHASHED_EMAIL": "e@x.com", "DEHASHED_API_KEY": "k"}),
            patch.object(crawler, "get", new=capturing_get),
        ):
            await crawler.scrape("  victim@example.com  ")

        assert len(captured_urls) == 1
        assert "victim@example.com" in captured_urls[0]
        assert "size=100" in captured_urls[0]
        assert "page=1" in captured_urls[0]


# ===========================================================================
# email_socialscan.py
# Lines: 34-70 (entire scrape method)
# ===========================================================================


class TestSocialscanCrawler:
    def _make(self):
        from modules.crawlers.email_socialscan import SocialscanCrawler
        return SocialscanCrawler()

    # Lines 34-43: socialscan not installed → ImportError path
    @pytest.mark.asyncio
    async def test_scrape_socialscan_not_installed(self):
        """Lines 36-43: ImportError on socialscan import → error='socialscan_not_installed'."""
        crawler = self._make()

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "socialscan.util":
                raise ImportError("No module named 'socialscan'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.error == "socialscan_not_installed"

    # Lines 46-58: QueryHandler().run() raises an exception
    @pytest.mark.asyncio
    async def test_scrape_query_handler_raises(self):
        """Lines 50-58: QueryHandler.run raises → found=False, error set."""
        crawler = self._make()

        mock_platforms = MagicMock()
        mock_platforms.__iter__ = MagicMock(return_value=iter(["twitter", "github"]))

        mock_query_class = MagicMock(side_effect=lambda q, p: MagicMock())
        mock_handler = MagicMock()
        mock_handler.run = AsyncMock(side_effect=RuntimeError("network failure"))

        mock_handler_class = MagicMock(return_value=mock_handler)

        mock_socialscan = MagicMock()
        mock_socialscan.Platforms = mock_platforms
        mock_socialscan.Query = mock_query_class
        mock_socialscan.QueryHandler = mock_handler_class

        with patch.dict("sys.modules", {"socialscan": mock_socialscan, "socialscan.util": mock_socialscan}):
            result = await crawler.scrape("test@example.com")

        assert result.found is False
        assert result.error == "network failure"

    # Lines 60-76: results with mix of registered/available/unknown
    @pytest.mark.asyncio
    async def test_scrape_results_registered_and_available(self):
        """Lines 60-77: results parsed; registered_on populated → found=True."""
        crawler = self._make()

        # Build mock result objects
        def _make_scan_result(platform_val, available):
            r = MagicMock()
            r.platform = MagicMock()
            r.platform.value = platform_val
            r.available = available
            return r

        mock_results = [
            _make_scan_result("twitter", False),   # registered (available=False)
            _make_scan_result("github", True),     # available (available=True)
            _make_scan_result("instagram", None),  # unknown
        ]

        mock_handler = MagicMock()
        mock_handler.run = AsyncMock(return_value=mock_results)
        mock_handler_class = MagicMock(return_value=mock_handler)

        # Build a list-like Platforms enum mock
        mock_platforms = ["twitter", "github", "instagram"]
        mock_query_class = MagicMock(side_effect=lambda q, p: MagicMock())

        mock_util = MagicMock()
        mock_util.Platforms = mock_platforms
        mock_util.Query = mock_query_class
        mock_util.QueryHandler = mock_handler_class

        with patch.dict("sys.modules", {"socialscan": mock_util, "socialscan.util": mock_util}):
            result = await crawler.scrape("testuser")

        assert result.found is True
        assert "twitter" in result.data["registered_on"]
        assert "github" in result.data["available_on"]
        assert result.data["checked_count"] == 3

    # Lines 60-76: all platforms available → found=False
    @pytest.mark.asyncio
    async def test_scrape_all_available(self):
        """Lines 60-77: no registered platforms → found=False."""
        crawler = self._make()

        def _make_scan_result(platform_val, available):
            r = MagicMock()
            r.platform = MagicMock()
            r.platform.value = platform_val
            r.available = available
            return r

        mock_results = [
            _make_scan_result("twitter", True),
            _make_scan_result("github", True),
        ]

        mock_handler = MagicMock()
        mock_handler.run = AsyncMock(return_value=mock_results)
        mock_handler_class = MagicMock(return_value=mock_handler)

        mock_platforms = ["twitter", "github"]
        mock_query_class = MagicMock(side_effect=lambda q, p: MagicMock())

        mock_util = MagicMock()
        mock_util.Platforms = mock_platforms
        mock_util.Query = mock_query_class
        mock_util.QueryHandler = mock_handler_class

        with patch.dict("sys.modules", {"socialscan": mock_util, "socialscan.util": mock_util}):
            result = await crawler.scrape("freeuser")

        assert result.found is False
        assert result.data["registered_on"] == []
        assert result.data["available_on"] == ["twitter", "github"]

    # Lines 63: platform has no .value — uses str() fallback
    @pytest.mark.asyncio
    async def test_scrape_platform_no_value_attr(self):
        """Line 63: platform without .value → str(res.platform) used."""
        crawler = self._make()

        # platform has no 'value' attribute
        r = MagicMock(spec=[])  # spec=[] means no attributes
        r.available = False
        # str(r.platform) will be a MagicMock repr — but the key test is no AttributeError
        r2 = MagicMock()
        del r2.platform  # remove platform attr
        # Easier approach: create an object whose platform has no .value
        class FakePlatform:
            def __str__(self):
                return "fakebook"

        res = MagicMock()
        res.platform = FakePlatform()
        res.available = False

        mock_handler = MagicMock()
        mock_handler.run = AsyncMock(return_value=[res])
        mock_handler_class = MagicMock(return_value=mock_handler)

        mock_util = MagicMock()
        mock_util.Platforms = ["fakebook"]
        mock_util.Query = MagicMock(side_effect=lambda q, p: MagicMock())
        mock_util.QueryHandler = mock_handler_class

        with patch.dict("sys.modules", {"socialscan": mock_util, "socialscan.util": mock_util}):
            result = await crawler.scrape("testuser")

        assert result.found is True
        assert "fakebook" in result.data["registered_on"]

    # Empty result list → found=False
    @pytest.mark.asyncio
    async def test_scrape_empty_results(self):
        """No results from QueryHandler → found=False, checked_count=0."""
        crawler = self._make()

        mock_handler = MagicMock()
        mock_handler.run = AsyncMock(return_value=[])
        mock_handler_class = MagicMock(return_value=mock_handler)

        mock_util = MagicMock()
        mock_util.Platforms = []
        mock_util.Query = MagicMock(side_effect=lambda q, p: MagicMock())
        mock_util.QueryHandler = mock_handler_class

        with patch.dict("sys.modules", {"socialscan": mock_util, "socialscan.util": mock_util}):
            result = await crawler.scrape("ghost@example.com")

        assert result.found is False
        assert result.data["checked_count"] == 0
        assert result.data["registered_on"] == []
