"""
test_social_wave4.py — Branch-coverage gap tests for social crawlers (wave 4).

Crawlers covered:
  social_spotify, social_twitch, social_steam, reddit,
  instagram, pinterest, facebook, discord, snapchat, linkedin, twitter

Each test targets specific uncovered lines identified in the coverage report.
All HTTP / Playwright I/O is mocked so no network calls are made.
"""

from __future__ import annotations

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
# social_spotify.py — lines 163-164, 173-174, 243-244
# ===========================================================================


class TestSpotifyCrawler:
    def _make_crawler(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        c = SpotifyCrawler()
        return c

    def _patch_settings(self, crawler):
        """Inject fake credentials so the 'not_configured' branch is skipped."""
        crawler._spotify_client_id = "fake_id"
        crawler._spotify_client_secret = "fake_secret"

    # --- lines 163-164: pl_resp.json() raises, except block silently passes ---
    @pytest.mark.asyncio
    async def test_playlists_json_error_is_swallowed(self):
        """Lines 163-164: playlist JSON parse failure is silently ignored."""
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()

        user_json = {
            "id": "testuser",
            "display_name": "Test User",
            "followers": {"total": 10},
            "images": [],
            "external_urls": {"spotify": "https://open.spotify.com/user/testuser"},
            "type": "user",
            "uri": "spotify:user:testuser",
        }
        user_resp = _mock_resp(200, json_data=user_json)
        pl_resp = _mock_resp(200)
        pl_resp.json.side_effect = ValueError("bad pl json")

        token_resp = _mock_resp(200, json_data={"access_token": "tok"})

        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "cid"
            mock_settings.spotify_client_secret = "csec"
            # token uses self.post; user + playlist use self.get
            with patch.object(crawler, "post", new=AsyncMock(return_value=token_resp)):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[user_resp, pl_resp]),
                ):
                    result = await crawler.scrape("testuser")

        assert result.found is True
        assert result.data.get("playlists") == []

    # --- lines 173-174: user_resp.json() raises, outer except, falls through ---
    @pytest.mark.asyncio
    async def test_user_json_parse_error_falls_to_artist_search(self):
        """Lines 173-174: user JSON parse error → falls back to artist search."""
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()

        user_resp = _mock_resp(200)
        user_resp.json.side_effect = ValueError("bad user json")

        token_resp = _mock_resp(200, json_data={"access_token": "tok"})
        search_resp = _mock_resp(200, json_data={"artists": {"items": []}})

        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "cid"
            mock_settings.spotify_client_secret = "csec"
            # token uses self.post; user + search use self.get
            with patch.object(crawler, "post", new=AsyncMock(return_value=token_resp)):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[user_resp, search_resp]),
                ):
                    result = await crawler.scrape("testuser")

        # artist search returned empty items → not found
        assert result.found is False

    # --- lines 243-244 (_get_access_token): non-200 or None resp returns None ---
    @pytest.mark.asyncio
    async def test_get_access_token_none_resp(self):
        """Lines 238-240: _get_access_token when resp is None → auth_failed."""
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()

        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "cid"
            mock_settings.spotify_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("anyuser")

        assert result.data.get("error") == "auth_failed"

    @pytest.mark.asyncio
    async def test_get_access_token_status_500(self):
        """Lines 238-240: _get_access_token non-200 status returns None → auth_failed."""
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        bad_resp = _mock_resp(500)

        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "cid"
            mock_settings.spotify_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=bad_resp)):
                result = await crawler.scrape("anyuser")

        assert result.data.get("error") == "auth_failed"


# ===========================================================================
# social_twitch.py — lines 169-170, 188-189, 216-217
# ===========================================================================


class TestTwitchCrawler:
    def _make_crawler(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        return TwitchCrawler()

    def _token_resp(self):
        return _mock_resp(200, json_data={"access_token": "twitch_tok"})

    def _user_resp(self):
        return _mock_resp(
            200,
            json_data={
                "data": [
                    {
                        "id": "123",
                        "login": "testuser",
                        "display_name": "TestUser",
                        "type": "",
                        "broadcaster_type": "affiliate",
                        "description": "desc",
                        "profile_image_url": "https://example.com/img.png",
                        "view_count": 1000,
                        "created_at": "2020-01-01T00:00:00Z",
                    }
                ]
            },
        )

    # --- lines 169-170: stream_resp.json() raises, except silently passes ---
    @pytest.mark.asyncio
    async def test_stream_json_error_silently_ignored(self):
        """Lines 169-170: stream JSON parse error is swallowed."""
        crawler = self._make_crawler()

        stream_resp = _mock_resp(200)
        stream_resp.json.side_effect = ValueError("bad stream json")

        ch_resp = _mock_resp(200, json_data={"data": []})

        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csec"
            # token via self.post, rest via self.get
            with patch.object(crawler, "post", new=AsyncMock(return_value=self._token_resp())):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[self._user_resp(), stream_resp, ch_resp]),
                ):
                    result = await crawler.scrape("testuser")

        assert result.found is True
        assert result.data.get("stream") is None
        assert result.data.get("is_live") is False

    # --- lines 188-189: channel resp.json() raises, except silently passes ---
    @pytest.mark.asyncio
    async def test_channel_json_error_silently_ignored(self):
        """Lines 188-189: channel JSON parse error is swallowed."""
        crawler = self._make_crawler()

        stream_resp = _mock_resp(200, json_data={"data": []})
        ch_resp = _mock_resp(200)
        ch_resp.json.side_effect = ValueError("bad ch json")

        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=self._token_resp())):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[self._user_resp(), stream_resp, ch_resp]),
                ):
                    result = await crawler.scrape("testuser")

        assert result.found is True
        assert result.data.get("channel") is None

    # --- lines 216-217: _get_app_token resp None or non-200 → returns None ---
    @pytest.mark.asyncio
    async def test_get_app_token_none_resp_returns_auth_failed(self):
        """Lines 216-217: token request returns None → auth_failed."""
        crawler = self._make_crawler()

        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csec"
            # _get_app_token calls self.post
            with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("testuser")

        assert result.data.get("error") == "auth_failed"

    @pytest.mark.asyncio
    async def test_get_app_token_bad_status_returns_auth_failed(self):
        """Lines 216-217: token request 500 status → auth_failed."""
        crawler = self._make_crawler()

        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(500))):
                result = await crawler.scrape("testuser")

        assert result.data.get("error") == "auth_failed"


# ===========================================================================
# social_steam.py — lines 207, 211-212
# ===========================================================================


class TestSteamCrawler:
    def _make_crawler(self):
        from modules.crawlers.social_steam import SteamCrawler

        return SteamCrawler()

    def _xml_resp(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <steamID64>76561198000000000</steamID64>
  <steamID><![CDATA[gaben]]></steamID>
  <onlineState>online</onlineState>
  <privacyState>public</privacyState>
  <headline></headline>
  <location></location>
  <realname></realname>
  <summary><![CDATA[Valve founder]]></summary>
  <memberSince>February 10, 2003</memberSince>
  <avatarIcon>https://example.com/avatar.jpg</avatarIcon>
</profile>"""
        return _mock_resp(200, text=xml)

    # --- line 207: _fetch_player_summary resp None or non-200 → returns None ---
    @pytest.mark.asyncio
    async def test_fetch_player_summary_none_resp(self):
        """Line 207: _fetch_player_summary when resp is None returns None."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._fetch_player_summary("apikey", "76561198000000000")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_player_summary_non200(self):
        """Line 207: _fetch_player_summary when resp is non-200 returns None."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
            result = await crawler._fetch_player_summary("apikey", "76561198000000000")

        assert result is None

    # --- lines 211-212: _fetch_player_summary json raises → returns None ---
    @pytest.mark.asyncio
    async def test_fetch_player_summary_json_error(self):
        """Lines 211-212: _fetch_player_summary JSON parse error returns None."""
        crawler = self._make_crawler()
        bad_resp = _mock_resp(200)
        bad_resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            result = await crawler._fetch_player_summary("apikey", "76561198000000000")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_player_summary_empty_players(self):
        """Lines 211-212: _fetch_player_summary with empty players list returns None."""
        crawler = self._make_crawler()
        resp = _mock_resp(200, json_data={"response": {"players": []}})

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._fetch_player_summary("apikey", "76561198000000000")

        assert result is None


# ===========================================================================
# reddit.py — lines 41-42, 57-58
# ===========================================================================


class TestRedditCrawler:
    def _make_crawler(self):
        from modules.crawlers.reddit import RedditCrawler

        return RedditCrawler()

    # --- lines 41-42: response.json() raises → parse_error ---
    @pytest.mark.asyncio
    async def test_json_parse_error(self):
        """Lines 41-42: JSON parse failure returns parse_error."""
        crawler = self._make_crawler()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("someuser")

        assert result.found is False
        assert result.data.get("error") == "parse_error"

    # --- lines 57-58: posts_resp.json() raises, except silently passes ---
    @pytest.mark.asyncio
    async def test_posts_json_error_silently_ignored(self):
        """Lines 57-58: posts JSON parse error is swallowed, result still found."""
        crawler = self._make_crawler()

        about_json = {
            "data": {
                "name": "t2_abc123",
                "icon_img": "",
                "created_utc": 1609459200.0,
                "link_karma": 100,
                "comment_karma": 200,
                "is_gold": False,
                "is_mod": False,
                "has_verified_email": True,
                "subreddit": {"public_description": "my bio"},
            }
        }
        about_resp = _mock_resp(200, json_data=about_json)

        posts_resp = _mock_resp(200)
        posts_resp.json.side_effect = ValueError("bad posts json")

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[about_resp, posts_resp])):
            result = await crawler.scrape("someuser")

        assert result.found is True
        # recent_posts key should not exist or be absent (parse failed silently)
        assert "recent_posts" not in result.data


# ===========================================================================
# instagram.py — lines 85, 90-91, 103-104
# ===========================================================================


class TestInstagramParseCount:
    """Lines 103-104: _parse_count with non-numeric suffix-less string."""

    def test_parse_count_invalid_no_suffix(self):
        """Lines 103-104: ValueError caught, returns None for bad no-suffix string."""
        from modules.crawlers.instagram import _parse_count

        result = _parse_count("abc")
        assert result is None

    def test_parse_count_invalid_suffix(self):
        """Line 85 region: ValueError caught for bad suffix value."""
        from modules.crawlers.instagram import _parse_count

        result = _parse_count("abcK")
        assert result is None

    def test_parse_count_valid_k(self):
        from modules.crawlers.instagram import _parse_count

        assert _parse_count("1.5K") == 1500

    def test_parse_count_valid_m(self):
        from modules.crawlers.instagram import _parse_count

        assert _parse_count("2M") == 2_000_000

    def test_parse_count_phone_in_bio(self):
        """Line 85: phone_match branch — ensures phone extracted from og_desc."""
        # This is a unit test on _extract_profile behaviour via mock page
        import asyncio

        from modules.crawlers.instagram import InstagramCrawler

        crawler = InstagramCrawler.__new__(InstagramCrawler)
        crawler.platform = "instagram"
        crawler.source_reliability = 0.55

        page = MagicMock()
        page.get_attribute = AsyncMock(
            side_effect=[
                "1.5K Followers, 100 Following, 10 Posts",  # meta description
                "Contact +1 555-867-5309 for info",  # og:description with phone
            ]
        )
        page.title = AsyncMock(return_value="John Doe (@johndoe) • Instagram photos and videos")
        page.content = AsyncMock(return_value="<html></html>")

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_profile(page, "johndoe")
        )
        assert result.get("phone") is not None

    def test_parse_count_email_in_bio(self):
        """Line 82 region: email extraction from og_desc."""
        import asyncio

        from modules.crawlers.instagram import InstagramCrawler

        crawler = InstagramCrawler.__new__(InstagramCrawler)
        crawler.platform = "instagram"
        crawler.source_reliability = 0.55

        page = MagicMock()
        page.get_attribute = AsyncMock(
            side_effect=[
                "",  # meta description — no followers
                "Email me at hello@example.com",  # og:description with email
            ]
        )
        page.title = AsyncMock(return_value="Jane (@jane) • Instagram photos and videos")
        page.content = AsyncMock(return_value="<html></html>")

        result = asyncio.get_event_loop().run_until_complete(crawler._extract_profile(page, "jane"))
        assert result.get("email") == "hello@example.com"

    def test_extract_profile_exception_returns_partial(self):
        """Lines 90-91: exception in _extract_profile is caught, returns partial data."""
        import asyncio

        from modules.crawlers.instagram import InstagramCrawler

        crawler = InstagramCrawler.__new__(InstagramCrawler)
        crawler.platform = "instagram"
        crawler.source_reliability = 0.55

        page = MagicMock()
        page.get_attribute = AsyncMock(side_effect=Exception("playwright error"))
        page.title = AsyncMock(return_value="")
        page.content = AsyncMock(return_value="<html></html>")

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_profile(page, "testhandle")
        )
        # Should return dict with at least the handle
        assert result["handle"] == "testhandle"


# ===========================================================================
# pinterest.py — lines 76-80
# ===========================================================================


class TestPinterestCrawler:
    def _make_crawler(self):
        from modules.crawlers.pinterest import PinterestCrawler

        return PinterestCrawler()

    # --- lines 76-77: follower count ValueError caught, pass ---
    def test_parse_meta_follower_count_invalid(self):
        """Lines 76-77: follower count int() raises ValueError — silently ignored."""
        from bs4 import BeautifulSoup

        from modules.crawlers.pinterest import PinterestCrawler

        crawler = PinterestCrawler.__new__(PinterestCrawler)
        html = """<html><head>
          <meta property="og:title" content="Test User" />
          <meta property="og:description" content="abc,def followers here" />
        </head></html>"""
        soup = BeautifulSoup(html, "html.parser")
        data = crawler._parse_meta(soup, "testuser")
        assert data["display_name"] == "Test User"
        # follower_count not set because parse failed
        assert "follower_count" not in data

    # --- lines 79-80: exception in _parse_meta is caught ---
    def test_parse_meta_exception_caught(self):
        """Lines 79-80: any exception in _parse_meta is caught, returns partial data."""
        from modules.crawlers.pinterest import PinterestCrawler

        crawler = PinterestCrawler.__new__(PinterestCrawler)
        bad_soup = MagicMock()
        bad_soup.find.side_effect = Exception("boom")
        data = crawler._parse_meta(bad_soup, "testuser")
        assert data["handle"] == "testuser"

    # --- follower_count successfully parsed ---
    def test_parse_meta_follower_count_valid(self):
        """Lines 71-75: valid follower count is parsed correctly."""
        from bs4 import BeautifulSoup

        from modules.crawlers.pinterest import PinterestCrawler

        crawler = PinterestCrawler.__new__(PinterestCrawler)
        html = """<html><head>
          <meta property="og:title" content="My User" />
          <meta property="og:description" content="1,234 followers on Pinterest" />
        </head></html>"""
        soup = BeautifulSoup(html, "html.parser")
        data = crawler._parse_meta(soup, "myuser")
        assert data["follower_count"] == 1234


# ===========================================================================
# facebook.py — lines 71-72
# ===========================================================================


class TestFacebookExtractMobile:
    # --- lines 71-72: exception in _extract_mobile is caught ---
    def test_extract_mobile_exception_caught(self):
        """Lines 71-72: exception in _extract_mobile is caught, returns partial data."""
        import asyncio

        from modules.crawlers.facebook import FacebookCrawler

        crawler = FacebookCrawler.__new__(FacebookCrawler)
        crawler.platform = "facebook"
        crawler.source_reliability = 0.60

        page = MagicMock()
        page.title = AsyncMock(side_effect=Exception("playwright crash"))
        page.query_selector = AsyncMock(return_value=None)

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_mobile(page, "testhandle", "some content")
        )
        assert result["handle"] == "testhandle"

    def test_extract_mobile_location_parsed(self):
        """Line 68-69: location extracted from JSON-like content."""
        import asyncio

        from modules.crawlers.facebook import FacebookCrawler

        crawler = FacebookCrawler.__new__(FacebookCrawler)
        crawler.platform = "facebook"
        crawler.source_reliability = 0.60

        page = MagicMock()
        page.title = AsyncMock(return_value="Test Page | Facebook")
        page.query_selector = AsyncMock(return_value=None)

        content = '"location": "New York"'

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_mobile(page, "testhandle", content)
        )
        assert result.get("location") == "New York"


# ===========================================================================
# discord.py — lines 93-94
# ===========================================================================


class TestDiscordCrawler:
    def _make_crawler(self):
        from modules.crawlers.discord import DiscordCrawler

        return DiscordCrawler()

    # --- lines 93-94: snowflake_to_datetime raises, except silently passes ---
    def test_build_data_invalid_snowflake_no_created_at(self):
        """Lines 93-94: non-numeric snowflake in _build_data → except silently passes."""
        from modules.crawlers.discord import DiscordCrawler

        crawler = DiscordCrawler.__new__(DiscordCrawler)
        # Passing a non-numeric snowflake string to trigger int() ValueError
        payload = {"username": "user1", "discriminator": "0001", "bot": False, "avatar": None}
        data = crawler._build_data("not-a-number", payload)
        assert data["username"] == "user1"
        assert "created_at" not in data

    def test_build_data_with_avatar(self):
        """Line 88-89: avatar_url is set when avatar hash present."""
        from modules.crawlers.discord import DiscordCrawler

        crawler = DiscordCrawler.__new__(DiscordCrawler)
        payload = {
            "id": "123456789012345678",
            "username": "user1",
            "discriminator": "0001",
            "bot": False,
            "avatar": "abc123hash",
        }
        data = crawler._build_data("123456789012345678", payload)
        assert "avatar_url" in data
        assert "abc123hash" in data["avatar_url"]


# ===========================================================================
# snapchat.py — lines 85-86
# ===========================================================================


class TestSnapchatCrawler:
    # --- lines 85-86: exception in _parse_meta is caught ---
    def test_parse_meta_exception_caught(self):
        """Lines 85-86: exception in _parse_meta is caught, returns partial data."""
        from modules.crawlers.snapchat import SnapchatCrawler

        crawler = SnapchatCrawler.__new__(SnapchatCrawler)
        bad_soup = MagicMock()
        bad_soup.find.side_effect = Exception("soup error")
        data = crawler._parse_meta(bad_soup, "testuser")
        assert data["handle"] == "testuser"
        assert "display_name" not in data

    def test_parse_meta_avatar_and_bio(self):
        """Lines 76-83: avatar and bio are populated from OG tags."""
        from bs4 import BeautifulSoup

        from modules.crawlers.snapchat import SnapchatCrawler

        crawler = SnapchatCrawler.__new__(SnapchatCrawler)
        html = """<html><head>
          <meta property="og:title" content="Cool User on Snapchat" />
          <meta property="og:image" content="https://example.com/snap.jpg" />
          <meta property="og:description" content="My snap bio" />
        </head></html>"""
        soup = BeautifulSoup(html, "html.parser")
        data = crawler._parse_meta(soup, "cooluser")
        assert data["avatar_url"] == "https://example.com/snap.jpg"
        assert data["bio"] == "My snap bio"


# ===========================================================================
# linkedin.py — lines 81-84
# ===========================================================================


class TestLinkedInCrawler:
    # --- lines 83-84: exception in _extract is caught ---
    def test_extract_exception_caught(self):
        """Lines 83-84: exception in _extract is caught, returns partial data."""
        import asyncio

        from modules.crawlers.linkedin import LinkedInCrawler

        crawler = LinkedInCrawler.__new__(LinkedInCrawler)
        crawler.platform = "linkedin"
        crawler.source_reliability = 0.75

        page = MagicMock()
        page.title = AsyncMock(side_effect=Exception("playwright crash"))
        page.query_selector = AsyncMock(return_value=None)
        page.url = "https://www.linkedin.com/in/testuser/"

        result = asyncio.get_event_loop().run_until_complete(crawler._extract(page, "testuser"))
        assert result["handle"] == "testuser"

    # --- lines 78-81: connection count parsed from .top-card__connections-count ---
    def test_extract_connections_count(self):
        """Lines 79-81: connections count extracted if element exists."""
        import asyncio

        from modules.crawlers.linkedin import LinkedInCrawler

        crawler = LinkedInCrawler.__new__(LinkedInCrawler)
        crawler.platform = "linkedin"
        crawler.source_reliability = 0.75

        conn_elem = MagicMock()
        conn_elem.inner_text = AsyncMock(return_value="500+ connections")

        page = MagicMock()
        page.title = AsyncMock(return_value="John Doe | LinkedIn")
        page.query_selector = AsyncMock(
            side_effect=[None, None, conn_elem]  # headline, location, connections
        )
        page.url = "https://www.linkedin.com/in/johndoe/"

        result = asyncio.get_event_loop().run_until_complete(crawler._extract(page, "johndoe"))
        assert result.get("connections") == "500+ connections"


# ===========================================================================
# twitter.py — lines 101-102
# ===========================================================================


class TestTwitterCrawler:
    # --- lines 101-102: exception in _parse_profile is caught ---
    def test_parse_profile_exception_caught(self):
        """Lines 101-102: exception in _parse_profile is caught, returns partial data."""
        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler.__new__(TwitterCrawler)
        bad_soup = MagicMock()
        bad_soup.find.side_effect = Exception("soup exploded")
        bad_soup.find_all.side_effect = Exception("soup exploded")

        data = crawler._parse_profile(bad_soup, "testhandle")
        assert data["handle"] == "testhandle"

    def test_parse_profile_location_and_join_date(self):
        """Lines 93-99: location and joined date populated from soup."""
        from bs4 import BeautifulSoup

        from modules.crawlers.twitter import TwitterCrawler

        crawler = TwitterCrawler.__new__(TwitterCrawler)
        html = """<html><body>
          <div class="profile-card-fullname">Test User</div>
          <div class="profile-bio">Bio text here</div>
          <div class="profile-location">San Francisco, CA</div>
          <div class="profile-joindate">Joined January 2015</div>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        data = crawler._parse_profile(soup, "testuser")
        assert data.get("location") == "San Francisco, CA"
        assert data.get("profile_created_at_str") == "Joined January 2015"


# ===========================================================================
# instagram.py — missing branches: 67→74, 71→74, 75→87
# ===========================================================================


class TestInstagramBranchGaps:
    # --- branch 67→74: title has no "•" so name_part block is skipped ---
    def test_extract_profile_no_bullet_in_title(self):
        """Branch 67→74: title without '•' skips name extraction, still extracts og_desc."""
        import asyncio

        from modules.crawlers.instagram import InstagramCrawler

        crawler = InstagramCrawler.__new__(InstagramCrawler)
        crawler.platform = "instagram"
        crawler.source_reliability = 0.55

        page = MagicMock()
        page.get_attribute = AsyncMock(
            side_effect=[
                "",  # meta description
                "A bio with no bullet title",  # og:description
            ]
        )
        # Title without "•" — exercises 67→74 False branch
        page.title = AsyncMock(return_value="Instagram Profile Page")
        page.content = AsyncMock(return_value="<html></html>")

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_profile(page, "someuser")
        )
        assert result["handle"] == "someuser"
        assert "display_name" not in result
        assert result.get("bio") == "A bio with no bullet title"

    # --- branch 71→74: name_part stripped to empty string, not set ---
    def test_extract_profile_name_part_empty_after_strip(self):
        """Branch 71→74: handle-only title after regex strip yields empty name_part."""
        import asyncio

        from modules.crawlers.instagram import InstagramCrawler

        crawler = InstagramCrawler.__new__(InstagramCrawler)
        crawler.platform = "instagram"
        crawler.source_reliability = 0.55

        page = MagicMock()
        page.get_attribute = AsyncMock(side_effect=["", ""])
        # Title where everything before "•" is just the @handle — after regex strip: empty
        page.title = AsyncMock(return_value="(@onlyhandle) • Instagram photos and videos")
        page.content = AsyncMock(return_value="<html></html>")

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_profile(page, "onlyhandle")
        )
        assert "display_name" not in result

    # --- branch 75→87: og_desc is empty, bio block is skipped ---
    def test_extract_profile_empty_og_desc(self):
        """Branch 75→87: og:description is empty string, bio not set, skips to content."""
        import asyncio

        from modules.crawlers.instagram import InstagramCrawler

        crawler = InstagramCrawler.__new__(InstagramCrawler)
        crawler.platform = "instagram"
        crawler.source_reliability = 0.55

        page = MagicMock()
        page.get_attribute = AsyncMock(side_effect=["", ""])  # both meta desc and og:desc empty
        page.title = AsyncMock(return_value="")
        page.content = AsyncMock(return_value='<html>is_verified":true</html>')

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_profile(page, "verifieduser")
        )
        assert "bio" not in result
        assert result.get("is_verified") is True


# ===========================================================================
# facebook.py — missing branch: 52→55
# ===========================================================================


class TestFacebookBranchGaps:
    # --- branch 52→55: title has no "Facebook" → display_name not set ---
    def test_extract_mobile_title_no_facebook_keyword(self):
        """Branch 52→55: title exists but 'Facebook' not in it → display_name not set."""
        import asyncio

        from modules.crawlers.facebook import FacebookCrawler

        crawler = FacebookCrawler.__new__(FacebookCrawler)
        crawler.platform = "facebook"
        crawler.source_reliability = 0.60

        page = MagicMock()
        # Title present but no "Facebook" keyword → if title and "Facebook" in title: False
        page.title = AsyncMock(return_value="Some Unrelated Page Title")
        page.query_selector = AsyncMock(return_value=None)

        result = asyncio.get_event_loop().run_until_complete(
            crawler._extract_mobile(page, "handle123", "")
        )
        assert result["handle"] == "handle123"
        assert "display_name" not in result


# ===========================================================================
# reddit.py — missing branch: 72→75
# ===========================================================================


class TestRedditBranchGap72:
    # --- branch 72→75: created_utc is None → created_at stays None ---
    def test_parse_no_created_utc(self):
        """Branch 72→75: created_utc is None → created_at remains None."""
        from modules.crawlers.reddit import RedditCrawler

        crawler = RedditCrawler.__new__(RedditCrawler)
        raw = {
            "name": "user1",
            "id": "abc",
            "link_karma": 10,
            "comment_karma": 20,
            # created_utc intentionally absent → .get() returns None
            "verified": False,
            "is_gold": False,
            "has_verified_email": True,
        }
        data = crawler._parse(raw, "user1")
        assert data["profile_created_at"] is None
        assert data["handle"] == "user1"


# ===========================================================================
# pinterest.py — missing branch: 68→81
# ===========================================================================


class TestPinterestBranchGap68:
    # --- branch 68→81: desc_tag exists but desc_tag.get("content") is falsy ---
    def test_parse_meta_desc_tag_no_content(self):
        """Branch 68→81: og:description tag present but content attr is empty."""
        from bs4 import BeautifulSoup

        from modules.crawlers.pinterest import PinterestCrawler

        crawler = PinterestCrawler.__new__(PinterestCrawler)
        # desc_tag exists but content="" (falsy) → inner if skipped, goes to 81 (end)
        html = """<html><head>
          <meta property="og:title" content="My Board" />
          <meta property="og:description" content="" />
        </head></html>"""
        soup = BeautifulSoup(html, "html.parser")
        data = crawler._parse_meta(soup, "myboard")
        assert data["display_name"] == "My Board"
        assert "bio" not in data
        assert "follower_count" not in data


# ===========================================================================
# social_twitch.py — missing branches: 155→173, 174→191, 176→191
# ===========================================================================


class TestTwitchBranchGaps:
    def _make_crawler(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        return TwitchCrawler()

    def _token_resp(self):
        return _mock_resp(200, json_data={"access_token": "tok"})

    def _user_resp(self):
        return _mock_resp(
            200,
            json_data={
                "data": [
                    {
                        "id": "456",
                        "login": "streamer",
                        "display_name": "Streamer",
                        "type": "",
                        "broadcaster_type": "partner",
                        "description": "A streamer",
                        "profile_image_url": "",
                        "view_count": 500,
                        "created_at": "2021-01-01T00:00:00Z",
                    }
                ]
            },
        )

    # --- branch 155→173: stream_resp is None or non-200 → stream stays None ---
    @pytest.mark.asyncio
    async def test_stream_resp_none_skips_stream_block(self):
        """Branch 155→173: stream_resp is None → stream block skipped, no live data."""
        crawler = self._make_crawler()

        ch_resp = _mock_resp(200, json_data={"data": []})

        with patch("modules.crawlers.social_twitch.settings") as ms:
            ms.twitch_client_id = "cid"
            ms.twitch_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=self._token_resp())):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[self._user_resp(), None, ch_resp]),
                ):
                    result = await crawler.scrape("streamer")

        assert result.found is True
        assert result.data.get("stream") is None
        assert result.data.get("is_live") is False

    # --- branch 174→191: user_id is empty string → channel block skipped ---
    @pytest.mark.asyncio
    async def test_no_user_id_skips_channel_fetch(self):
        """Branch 174→191: user_id is '' (falsy) → channel fetch skipped."""
        crawler = self._make_crawler()

        # user response with no "id" field → user_id = ""
        user_resp_no_id = _mock_resp(
            200,
            json_data={
                "data": [
                    {
                        "id": "",
                        "login": "noider",
                        "display_name": "NoId",
                        "type": "",
                        "broadcaster_type": "",
                        "description": "",
                        "profile_image_url": "",
                        "view_count": 0,
                        "created_at": "",
                    }
                ]
            },
        )
        stream_resp = _mock_resp(200, json_data={"data": []})

        with patch("modules.crawlers.social_twitch.settings") as ms:
            ms.twitch_client_id = "cid"
            ms.twitch_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=self._token_resp())):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[user_resp_no_id, stream_resp]),
                ):
                    result = await crawler.scrape("noider")

        assert result.found is True
        assert result.data.get("channel") is None

    # --- branch 176→191: ch_resp is None → channel block skipped ---
    @pytest.mark.asyncio
    async def test_ch_resp_none_skips_channel_block(self):
        """Branch 176→191: ch_resp is None → channel stays None."""
        crawler = self._make_crawler()

        stream_resp = _mock_resp(200, json_data={"data": []})

        with patch("modules.crawlers.social_twitch.settings") as ms:
            ms.twitch_client_id = "cid"
            ms.twitch_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=self._token_resp())):
                with patch.object(
                    crawler,
                    "get",
                    new=AsyncMock(side_effect=[self._user_resp(), stream_resp, None]),
                ):
                    result = await crawler.scrape("streamer")

        assert result.found is True
        assert result.data.get("channel") is None


# ===========================================================================
# linkedin.py — missing branches: 91→89, 93→97
# ===========================================================================


class TestLinkedInSkillBranches:
    # --- branch 91→89: skill element inner_text is empty → not appended, loops back ---
    # --- branch 93→97: all skills empty → skills list is empty, not set in data ---
    def test_extract_skills_all_empty_text(self):
        """Branches 91→89 and 93→97: skill elements with empty text — skills not added."""
        import asyncio

        from modules.crawlers.linkedin import LinkedInCrawler

        crawler = LinkedInCrawler.__new__(LinkedInCrawler)
        crawler.platform = "linkedin"
        crawler.source_reliability = 0.75

        # skill_el returns empty text → if text: False (91→89), then if skills: False (93→97)
        skill_el = MagicMock()
        skill_el.inner_text = AsyncMock(return_value="   ")  # blank text

        page = MagicMock()
        page.title = AsyncMock(return_value="John Doe | LinkedIn")
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(
            side_effect=[
                [skill_el],  # skill_els — non-empty list triggers outer if
                [],  # endorsement_els
            ]
        )
        page.url = "https://www.linkedin.com/in/johndoe/"

        result = asyncio.get_event_loop().run_until_complete(crawler._extract(page, "johndoe"))
        assert "skills" not in result


# ===========================================================================
# social_steam.py — missing branch: 183→193
# ===========================================================================


class TestSteamBranchGap183:
    # --- branch 183→193: api_key present but _fetch_player_summary returns None ---
    @pytest.mark.asyncio
    async def test_scrape_api_key_set_summary_none(self):
        """Branch 183→193: steam_api_key set but _fetch_player_summary returns None."""
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <steamID64>76561198000000001</steamID64>
  <steamID><![CDATA[testgamer]]></steamID>
  <onlineState>offline</onlineState>
  <privacyState>public</privacyState>
  <headline></headline>
  <location></location>
  <realname></realname>
  <summary><![CDATA[test bio]]></summary>
  <memberSince>January 1, 2015</memberSince>
  <avatarIcon>https://example.com/a.jpg</avatarIcon>
</profile>"""
        xml_resp = _mock_resp(200, text=xml)

        with patch("modules.crawlers.social_steam.settings") as ms:
            ms.steam_api_key = "fakekey"  # api_key is truthy
            with patch.object(crawler, "get", new=AsyncMock(return_value=xml_resp)):
                with patch.object(
                    crawler, "_fetch_player_summary", new=AsyncMock(return_value=None)
                ):
                    result = await crawler.scrape("testgamer")

        assert result.found is True
        # no real_name or country_code because summary was None
        assert "real_name" not in result.data.get("profile", {})


# ===========================================================================
# social_spotify.py — missing branch: 149→166
# ===========================================================================


class TestSpotifyBranchGap149:
    # --- branch 149→166: pl_resp is None → playlist block skipped, returns result ---
    @pytest.mark.asyncio
    async def test_playlist_resp_none_returns_result(self):
        """Branch 149→166: pl_resp is None → playlists stays [], result is found=True."""
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()

        user_json = {
            "id": "spotifyuser",
            "display_name": "Spotify User",
            "followers": {"total": 5},
            "images": [],
            "external_urls": {"spotify": "https://open.spotify.com/user/spotifyuser"},
            "type": "user",
            "uri": "spotify:user:spotifyuser",
        }
        user_resp = _mock_resp(200, json_data=user_json)
        token_resp = _mock_resp(200, json_data={"access_token": "tok"})

        with patch("modules.crawlers.social_spotify.settings") as ms:
            ms.spotify_client_id = "cid"
            ms.spotify_client_secret = "csec"
            with patch.object(crawler, "post", new=AsyncMock(return_value=token_resp)):
                with patch.object(
                    crawler,
                    "get",
                    # user_resp then None for pl_resp
                    new=AsyncMock(side_effect=[user_resp, None]),
                ):
                    result = await crawler.scrape("spotifyuser")

        assert result.found is True
        assert result.data.get("playlists") == []
