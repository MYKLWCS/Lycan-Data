"""
test_social_wave5.py — Branch-coverage gap tests for social crawlers (wave 5).

Crawlers covered:
  discord, instagram, snapchat, pinterest, facebook

Each test targets specific uncovered lines identified in the coverage report.
All HTTP / Playwright I/O is mocked — no network calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status=200, json_data=None, text="", raise_json=False):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text or ""
    if raise_json:
        resp.json.side_effect = ValueError("bad json")
    elif json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _playwright_ctx(content="", title="", url=""):
    """Return an async context manager that yields a mock Playwright page."""
    inner_page = AsyncMock()
    inner_page.content = AsyncMock(return_value=content)
    inner_page.title = AsyncMock(return_value=title)
    inner_page.url = url
    inner_page.get_attribute = AsyncMock(return_value=None)
    inner_page.query_selector = AsyncMock(return_value=None)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner_page)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, inner_page


# ===========================================================================
# DiscordCrawler — modules/crawlers/discord.py
# ===========================================================================


class TestDiscordCrawler:
    def _make_crawler(self):
        from modules.crawlers.discord import DiscordCrawler

        return DiscordCrawler()

    # ---- non-numeric identifier → immediate error --------------------------

    @pytest.mark.asyncio
    async def test_non_numeric_identifier_returns_error(self):
        crawler = self._make_crawler()
        result = await crawler.scrape("not_a_snowflake")
        assert result.found is False
        assert result.data.get("error") == "Discord requires numeric user ID (snowflake)"

    # ---- None response → http_error ----------------------------------------

    @pytest.mark.asyncio
    async def test_none_response_returns_http_error(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("123456789012345678")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # ---- 404 → found=False, no error (line 55) -----------------------------

    @pytest.mark.asyncio
    async def test_404_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123456789012345678")
        assert result.found is False
        assert result.error is None or result.error == ""

    # ---- non-200 (e.g. 429) → unexpected_status_N (line 58) ---------------

    @pytest.mark.asyncio
    async def test_non_200_returns_unexpected_status(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123456789012345678")
        assert result.found is False
        assert result.data.get("error") == "unexpected_status_429"

    @pytest.mark.asyncio
    async def test_503_returns_unexpected_status(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123456789012345678")
        assert result.found is False
        assert result.data.get("error") == "unexpected_status_503"

    # ---- JSON parse error (lines 66-68) ------------------------------------

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_json_parse_error(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, raise_json=True)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123456789012345678")
        assert result.found is False
        assert result.data.get("error") == "json_parse_error"

    # ---- 200 with valid payload → found=True -------------------------------

    @pytest.mark.asyncio
    async def test_200_with_payload_returns_found(self):
        crawler = self._make_crawler()
        payload = {
            "id": "123456789012345678",
            "username": "testuser",
            "discriminator": "0001",
            "avatar": "abc123",
            "bot": False,
        }
        resp = _mock_resp(status=200, json_data=payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123456789012345678")
        assert result.found is True
        assert result.data["username"] == "testuser"
        assert result.data["discriminator"] == "0001"
        assert "avatar_url" in result.data


# ===========================================================================
# InstagramCrawler — modules/crawlers/instagram.py
# ===========================================================================


class TestInstagramCrawler:
    def _make_crawler(self):
        from modules.crawlers.instagram import InstagramCrawler

        return InstagramCrawler()

    # ---- "Sorry, this page" → found=False (covered by wave4, included for completeness) ---

    @pytest.mark.asyncio
    async def test_page_not_available_returns_not_found(self):
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="Sorry, this page isn't available.")
        with patch.object(crawler, "page", return_value=ctx):
            result = await crawler.scrape("testuser")
        assert result.found is False
        assert result.error is None or result.error == ""

    # ---- "This Account is Private" → found=True, is_private=True (line 32-33) ---

    @pytest.mark.asyncio
    async def test_private_account_returns_found_private(self):
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="This Account is Private — some other content")
        with patch.object(crawler, "page", return_value=ctx):
            result = await crawler.scrape("privateuser")
        assert result.found is True
        assert result.data.get("is_private") is True

    @pytest.mark.asyncio
    async def test_private_account_lowercase_variant(self):
        """'This account is private' (lowercase) also triggers the private branch."""
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="This account is private")
        with patch.object(crawler, "page", return_value=ctx):
            result = await crawler.scrape("anotheruser")
        assert result.found is True
        assert result.data.get("is_private") is True

    # ---- no display_name + no follower_count → blocked_or_captcha (lines 37-39) ---

    @pytest.mark.asyncio
    async def test_no_data_returns_blocked_or_captcha(self):
        """Empty _extract_profile output → rotate_circuit + blocked_or_captcha."""
        crawler = self._make_crawler()
        # Content has no sentinel strings so we fall through to _extract_profile
        ctx, inner_page = _playwright_ctx(content="<html><body>Some generic page</body></html>")
        # _extract_profile is an instance method; patch it to return empty dict
        with patch.object(crawler, "page", return_value=ctx):
            with patch.object(crawler, "_extract_profile", new=AsyncMock(return_value={})):
                with patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate:
                    result = await crawler.scrape("blockeduser")
        assert result.found is False
        assert result.data.get("error") == "blocked_or_captcha"
        mock_rotate.assert_awaited_once()

    # ---- full success path --------------------------------------------------

    @pytest.mark.asyncio
    async def test_success_path_returns_found(self):
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="<html><body>Normal profile</body></html>")
        profile_data = {
            "handle": "realuser",
            "display_name": "Real User",
            "follower_count": 1500,
        }
        with patch.object(crawler, "page", return_value=ctx):
            with patch.object(
                crawler, "_extract_profile", new=AsyncMock(return_value=profile_data)
            ):
                result = await crawler.scrape("realuser")
        assert result.found is True
        assert result.data["display_name"] == "Real User"


# ===========================================================================
# SnapchatCrawler — modules/crawlers/snapchat.py
# ===========================================================================


class TestSnapchatCrawler:
    def _make_crawler(self):
        from modules.crawlers.snapchat import SnapchatCrawler

        return SnapchatCrawler()

    # ---- None response → http_error ----------------------------------------

    @pytest.mark.asyncio
    async def test_none_response_returns_http_error(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("someuser")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # ---- 404 → found=False, no error (line 33) -----------------------------

    @pytest.mark.asyncio
    async def test_404_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("ghost404")
        assert result.found is False
        assert not result.error

    # ---- NOT_FOUND_SENTINEL in body → found=False --------------------------

    @pytest.mark.asyncio
    async def test_not_found_sentinel_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="This Snapcode is not available right now")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("deleteduser")
        assert result.found is False
        assert not result.error

    # ---- 200 but no og:title → parse_failed (line 43) ----------------------

    @pytest.mark.asyncio
    async def test_no_display_name_returns_parse_failed(self):
        """200 HTML with no og:title → _parse_meta returns no display_name → parse_failed."""
        crawler = self._make_crawler()
        html_no_title = """
        <html><head>
        <meta property="og:image" content="https://example.com/img.png"/>
        </head><body><p>Some page</p></body></html>
        """
        resp = _mock_resp(status=200, text=html_no_title)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("noname")
        assert result.found is False
        assert result.data.get("error") == "parse_failed"

    # ---- 200 with og:title that is just "Snapchat" → parse_failed ----------

    @pytest.mark.asyncio
    async def test_title_only_snapchat_returns_parse_failed(self):
        """og:title that strips down to just 'Snapchat' is rejected as non-name."""
        crawler = self._make_crawler()
        html = """
        <html><head>
        <meta property="og:title" content="Snapchat"/>
        </head><body></body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("snaponly")
        assert result.found is False
        assert result.data.get("error") == "parse_failed"

    # ---- success path -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_valid_profile_returns_found(self):
        crawler = self._make_crawler()
        html = """
        <html><head>
        <meta property="og:title" content="John Doe on Snapchat"/>
        <meta property="og:image" content="https://snapchat.com/img.png"/>
        <meta property="og:description" content="Add me on Snapchat!"/>
        </head><body></body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("johndoe")
        assert result.found is True
        assert result.data["display_name"] == "John Doe"


# ===========================================================================
# PinterestCrawler — modules/crawlers/pinterest.py
# ===========================================================================


class TestPinterestCrawler:
    def _make_crawler(self):
        from modules.crawlers.pinterest import PinterestCrawler

        return PinterestCrawler()

    # ---- None response → http_error ----------------------------------------

    @pytest.mark.asyncio
    async def test_none_response_returns_http_error(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("someuser")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # ---- 404 → found=False, no error (line 32 area / actual line 34-35) ----

    @pytest.mark.asyncio
    async def test_404_returns_not_found(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("missinguser")
        assert result.found is False
        assert not result.error

    # ---- NOT_FOUND_SENTINEL in body → found=False --------------------------

    @pytest.mark.asyncio
    async def test_not_found_sentinel_in_body(self):
        crawler = self._make_crawler()
        resp = _mock_resp(status=200, text="This page doesn't exist — sorry")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("noprofile")
        assert result.found is False
        assert not result.error

    # ---- 200 but no og:title → parse_failed (line 45) ----------------------

    @pytest.mark.asyncio
    async def test_no_display_name_returns_parse_failed(self):
        """200 HTML with no og:title meta tag → parse_failed."""
        crawler = self._make_crawler()
        html = """
        <html><head>
        <meta property="og:image" content="https://i.pinimg.com/avatar.jpg"/>
        <meta property="og:description" content="123 followers, 45 following"/>
        </head><body></body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("noname")
        assert result.found is False
        assert result.data.get("error") == "parse_failed"

    # ---- success path with follower count in description -------------------

    @pytest.mark.asyncio
    async def test_valid_profile_with_followers_returns_found(self):
        crawler = self._make_crawler()
        html = """
        <html><head>
        <meta property="og:title" content="Jane Smith"/>
        <meta property="og:image" content="https://i.pinimg.com/img.jpg"/>
        <meta property="og:description" content="1,234 followers — Pinning great stuff"/>
        </head><body></body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("janesmith")
        assert result.found is True
        assert result.data["display_name"] == "Jane Smith"
        assert result.data.get("follower_count") == 1234


# ===========================================================================
# FacebookCrawler — modules/crawlers/facebook.py
# ===========================================================================


class TestFacebookCrawler:
    def _make_crawler(self):
        from modules.crawlers.facebook import FacebookCrawler

        return FacebookCrawler()

    # ---- login wall → delegates to _try_graph ------------------------------

    @pytest.mark.asyncio
    async def test_login_wall_calls_try_graph(self):
        """When page contains 'log in' + 'password', _try_graph is called."""
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(
            content="Please log in. Enter your password to continue."
        )
        mock_graph_result = MagicMock()
        mock_graph_result.found = True
        mock_graph_result.data = {"display_name": "Test Page"}
        with patch.object(crawler, "page", return_value=ctx):
            with patch.object(
                crawler, "_try_graph", new=AsyncMock(return_value=mock_graph_result)
            ) as mock_try:
                result = await crawler.scrape("testhandle")
        mock_try.assert_awaited_once_with("testhandle")
        assert result.found is True

    # ---- "page not found" in content → found=False (line 34-35) -----------

    @pytest.mark.asyncio
    async def test_page_not_found_returns_not_found(self):
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="Page not found — Facebook")
        with patch.object(crawler, "page", return_value=ctx):
            result = await crawler.scrape("missingpage")
        assert result.found is False
        assert result.error is None or result.error == ""

    @pytest.mark.asyncio
    async def test_content_not_found_returns_not_found(self):
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="Content not found on this server")
        with patch.object(crawler, "page", return_value=ctx):
            result = await crawler.scrape("anotherpage")
        assert result.found is False

    # ---- success: _extract_mobile called and CrawlerResult built -----------

    @pytest.mark.asyncio
    async def test_success_path_returns_found(self):
        crawler = self._make_crawler()
        ctx, _ = _playwright_ctx(content="<html><body>Public profile page here</body></html>")
        extract_data = {"handle": "mypage", "display_name": "My Page", "follower_count": 500}
        with patch.object(crawler, "page", return_value=ctx):
            with patch.object(
                crawler, "_extract_mobile", new=AsyncMock(return_value=extract_data)
            ):
                result = await crawler.scrape("mypage")
        assert result.found is True
        assert result.data["display_name"] == "My Page"

    # ---- _extract_mobile: bio extraction from about_elem (line 57) ---------

    @pytest.mark.asyncio
    async def test_extract_mobile_bio_from_about_elem(self):
        """about_elem truthy → inner_text() used as bio."""
        crawler = self._make_crawler()

        # Build a fake page with an about element
        page_mock = AsyncMock()
        page_mock.title = AsyncMock(return_value="Test Page | Facebook")

        about_mock = AsyncMock()
        about_mock.inner_text = AsyncMock(return_value="We are a test company.")
        page_mock.query_selector = AsyncMock(return_value=about_mock)

        content = "<html><body>no followers text here</body></html>"
        result = await crawler._extract_mobile(page_mock, "testpage", content)

        assert result["bio"] == "We are a test company."
        assert result["display_name"] == "Test Page"

    # ---- _extract_mobile: follower_count from content regex (lines 63-65) --

    @pytest.mark.asyncio
    async def test_extract_mobile_follower_count_from_content(self):
        """Follower match in content → _parse_count used for follower_count."""
        crawler = self._make_crawler()

        page_mock = AsyncMock()
        page_mock.title = AsyncMock(return_value="Brand Page | Facebook")
        page_mock.query_selector = AsyncMock(return_value=None)

        content = "Brand Page · 12,500 followers · some other info"
        result = await crawler._extract_mobile(page_mock, "brandpage", content)

        assert result.get("follower_count") == 12500

    @pytest.mark.asyncio
    async def test_extract_mobile_likes_count_from_content(self):
        """'likes' variant also triggers follower_count extraction."""
        crawler = self._make_crawler()

        page_mock = AsyncMock()
        page_mock.title = AsyncMock(return_value="Community | Facebook")
        page_mock.query_selector = AsyncMock(return_value=None)

        content = "500K likes · This page is about something"
        result = await crawler._extract_mobile(page_mock, "community", content)

        assert result.get("follower_count") == 500_000

    # ---- _try_graph: successful httpx call → CrawlerResult found=True ------

    @pytest.mark.asyncio
    async def test_try_graph_success(self):
        """httpx returns 200 with 'name' → CrawlerResult(found=True)."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"name": "John Doe", "fan_count": 1000, "about": "Bio text"}

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.crawlers.facebook.httpx.AsyncClient") as MockClient:
            MockClient.return_value = mock_client_instance
            result = await crawler._try_graph("testhandle")

        assert result.found is True
        assert result.data["display_name"] == "John Doe"
        assert result.data["follower_count"] == 1000

    # ---- _try_graph: 200 but no 'name' in response → login_wall -----------

    @pytest.mark.asyncio
    async def test_try_graph_200_no_name_returns_login_wall(self):
        """200 response but JSON has no 'name' key → falls through to login_wall."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": {"message": "access denied"}}

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.crawlers.facebook.httpx.AsyncClient") as MockClient:
            MockClient.return_value = mock_client_instance
            result = await crawler._try_graph("testhandle")

        assert result.found is False
        assert result.data.get("error") == "login_wall"

    # ---- _try_graph: httpx raises → login_wall (line 97-99) ---------------

    @pytest.mark.asyncio
    async def test_try_graph_exception_returns_login_wall(self):
        """httpx raises any exception → except block → login_wall."""
        crawler = self._make_crawler()

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(side_effect=Exception("network error"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.crawlers.facebook.httpx.AsyncClient") as MockClient:
            MockClient.return_value = mock_client_instance
            result = await crawler._try_graph("testhandle")

        assert result.found is False
        assert result.data.get("error") == "login_wall"

    # ---- _try_graph: non-200 status → login_wall ---------------------------

    @pytest.mark.asyncio
    async def test_try_graph_non_200_returns_login_wall(self):
        """Non-200 status from graph endpoint → falls through to login_wall."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {}

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.crawlers.facebook.httpx.AsyncClient") as MockClient:
            MockClient.return_value = mock_client_instance
            result = await crawler._try_graph("testhandle")

        assert result.found is False
        assert result.data.get("error") == "login_wall"
