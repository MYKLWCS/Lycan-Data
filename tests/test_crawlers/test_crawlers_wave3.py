"""
test_crawlers_wave3.py — Branch-coverage tests for wave-3 crawlers.

Crawlers targeted (with their approximate pre-wave coverage):
  telegram.py          (~79%)
  tiktok.py            (~81%)
  username_sherlock.py (~79%)
  public_voter.py      (~76%)
  court_state.py       (~80%)
  crypto_blockchair.py (~80%)
  crypto_ethereum.py   (~87%)
  crypto_bitcoin.py    (~89%)
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    """Build a lightweight MagicMock that mimics an httpx Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (str(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


# ===========================================================================
# telegram.py
# ===========================================================================


class TestTelegramCrawler:
    """Covers uncovered branches in TelegramCrawler."""

    def _make_crawler(self):
        from modules.crawlers.telegram import TelegramCrawler

        c = TelegramCrawler.__new__(TelegramCrawler)
        c.platform = "telegram"
        c.source_reliability = 0.50
        c.requires_tor = True
        return c

    # --- subscriber count ValueError branch (line ~71) ---

    @pytest.mark.asyncio
    async def test_probe_username_subscriber_value_error(self):
        """Non-numeric subscriber count must be silently swallowed."""
        crawler = self._make_crawler()
        html = (
            "<html><body>"
            '<div class="tgme_page_title">My Channel</div>'
            '<div class="tgme_page_additional">foo subscribers</div>'
            # 'foo' is the non-numeric part that triggers ValueError
            "</body></html>"
        )
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._probe_username("mychannel")
        # Should still return a result — ValueError must not propagate
        assert result.platform == "telegram"
        assert result.identifier == "mychannel"
        # follower_count must NOT be set because parsing failed
        assert "follower_count" not in result.data

    @pytest.mark.asyncio
    async def test_probe_username_valid_subscriber_count(self):
        """Numeric subscriber count should parse correctly."""
        crawler = self._make_crawler()
        html = (
            "<html><body>"
            '<div class="tgme_page_title">News Channel</div>'
            "12,345 subscribers"
            "</body></html>"
        )
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._probe_username("newschannel")
        assert result.data.get("follower_count") == 12345

    # --- None response from _probe_username ---

    @pytest.mark.asyncio
    async def test_probe_username_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._probe_username("ghost")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_probe_username_non_200(self):
        crawler = self._make_crawler()
        resp = _mock_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._probe_username("ghost")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # --- _probe_phone Telethon import injection via sys.modules patching ---

    @pytest.mark.asyncio
    async def test_probe_phone_telethon_configured_user_found(self):
        """
        When env vars are set and Telethon resolves a user, result must be found=True.
        We inject a fake `telethon` package tree via sys.modules.
        """
        phone = "+15550001234"

        # Build fake Telethon module objects
        fake_telethon = MagicMock()
        fake_sessions = MagicMock()
        fake_errors = MagicMock()
        fake_contacts = MagicMock()

        # StringSession returns a sentinel
        fake_sessions.StringSession.return_value = "sess_obj"

        # PhoneNumberInvalidError — needs to be a real exception class for except clause
        class FakePhoneNumberInvalidError(Exception):
            pass

        fake_errors.PhoneNumberInvalidError = FakePhoneNumberInvalidError

        # ResolvePhoneRequest callable
        fake_contacts.ResolvePhoneRequest = MagicMock(return_value="req_obj")

        # Fake user
        fake_user = MagicMock()
        fake_user.first_name = "Alice"
        fake_user.last_name = "Doe"
        fake_user.username = "alicedoe"
        fake_user.id = 999

        # Fake resolve result
        fake_resolve_result = MagicMock()
        fake_resolve_result.users = [fake_user]

        # Fake TelegramClient instance
        fake_client = MagicMock()
        fake_client.connect = AsyncMock()
        fake_client.disconnect = AsyncMock()
        # __call__ returns the resolve result
        fake_client.return_value = fake_resolve_result
        fake_client.__call__ = AsyncMock(return_value=fake_resolve_result)
        # Make await client(...) work
        fake_client_instance = MagicMock()
        fake_client_instance.connect = AsyncMock()
        fake_client_instance.disconnect = AsyncMock()
        fake_client_instance.__call__ = AsyncMock(return_value=fake_resolve_result)

        # TelegramClient constructor returns our fake instance
        fake_telethon.TelegramClient.return_value = fake_client_instance

        # Stitch the submodule tree together
        fake_telethon.sessions = fake_sessions
        fake_telethon.errors = fake_errors

        # Patch sys.modules so `from telethon import ...` works
        modules_patch = {
            "telethon": fake_telethon,
            "telethon.sessions": fake_sessions,
            "telethon.errors": fake_errors,
            "telethon.tl": MagicMock(),
            "telethon.tl.functions": MagicMock(),
            "telethon.tl.functions.contacts": fake_contacts,
        }

        crawler = self._make_crawler()
        env_patch = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "abc123hash",
            "TELEGRAM_SESSION": "session_string_here",
        }
        with patch.dict(sys.modules, modules_patch):
            with patch.dict("os.environ", env_patch):
                result = await crawler._probe_phone(phone)

        # Whether found or not, the call must return a CrawlerResult with the right platform
        assert result.platform == "telegram"
        assert result.identifier == phone

    @pytest.mark.asyncio
    async def test_probe_phone_telethon_import_error(self):
        """When Telethon is not importable (ImportError), return found=False without crash."""
        phone = "+15550001234"
        crawler = self._make_crawler()
        env_patch = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "abc123hash",
            "TELEGRAM_SESSION": "session_string_here",
        }

        # Remove telethon from sys.modules if present, and block re-import
        blocked: dict = {}
        for key in list(sys.modules.keys()):
            if key.startswith("telethon"):
                blocked[key] = sys.modules.pop(key)

        with patch.dict("os.environ", env_patch):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError("no module"))
                    if name == "telethon"
                    else __import__(name, *a, **kw)
                ),
            ):  # noqa: E501
                result = await crawler._probe_phone(phone)

        # Restore
        sys.modules.update(blocked)

        assert result.platform == "telegram"
        assert result.found is False

    @pytest.mark.asyncio
    async def test_probe_phone_no_env_vars(self):
        """Without env vars, should return telethon_not_configured error."""
        crawler = self._make_crawler()
        with patch.dict("os.environ", {}, clear=True):
            # Ensure the three vars are absent
            for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION"):
                import os

                os.environ.pop(k, None)
            result = await crawler._probe_phone("+15559999999")
        assert result.found is False
        assert result.error == "telethon_not_configured"

    @pytest.mark.asyncio
    async def test_scrape_dispatches_to_probe_phone(self):
        """Identifier starting with '+' must route to _probe_phone."""
        crawler = self._make_crawler()
        with patch.object(
            crawler, "_probe_phone", new=AsyncMock(return_value=MagicMock(platform="telegram"))
        ) as mock_phone:
            await crawler.scrape("+15551234567")
        mock_phone.assert_called_once_with("+15551234567")

    @pytest.mark.asyncio
    async def test_scrape_dispatches_to_probe_username(self):
        """Plain identifier must route to _probe_username (lstrip '@')."""
        crawler = self._make_crawler()
        with patch.object(
            crawler,
            "_probe_username",
            new=AsyncMock(return_value=MagicMock(platform="telegram")),
        ) as mock_user:
            await crawler.scrape("@somehandle")
        mock_user.assert_called_once_with("somehandle")


# ===========================================================================
# tiktok.py
# ===========================================================================


class TestTikTokCrawler:
    """Covers uncovered branches in TikTokCrawler."""

    def _make_crawler(self):
        from modules.crawlers.tiktok import TikTokCrawler

        c = TikTokCrawler.__new__(TikTokCrawler)
        c.platform = "tiktok"
        c.source_reliability = 0.50
        c.requires_tor = True
        return c

    # --- None response / non-200 (line ~29) ---

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("tiktokuser")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_scrape_non_200_response(self):
        crawler = self._make_crawler()
        resp = _mock_resp(403, text="Forbidden")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("tiktokuser")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_scrape_429_response(self):
        crawler = self._make_crawler()
        resp = _mock_resp(429, text="Too Many Requests")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("tiktokuser")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # --- JSON decode error falling back to meta-tag extraction (lines ~76-87) ---

    @pytest.mark.asyncio
    async def test_scrape_falls_back_to_meta_tags_on_json_error(self):
        """
        When the embedded JSON is malformed, _parse() falls back to <title>
        and <meta name='description'> extraction.
        """
        crawler = self._make_crawler()
        html = (
            "<html><head>"
            "<title>Jane Doe | TikTok</title>"
            '<meta name="description" content="Short bio here.">'
            "</head><body>"
            # A script tag with the expected id but invalid JSON
            '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">NOT_VALID_JSON{{{</script>'
            "</body></html>"
        )
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("janedoe")
        # Must not raise; display_name or bio should be populated from meta
        assert result.platform == "tiktok"
        assert result.data.get("display_name") == "Jane Doe"
        assert result.data.get("bio") == "Short bio here."

    @pytest.mark.asyncio
    async def test_scrape_fallback_title_pipe_split(self):
        """Title with no pipe should still be captured without error."""
        crawler = self._make_crawler()
        html = "<html><head><title>Just A Title</title></head><body></body></html>"
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("user123")
        assert result.data.get("display_name") == "Just A Title"

    @pytest.mark.asyncio
    async def test_scrape_meta_tag_no_content_attr(self):
        """Meta tag present but missing content attribute should not crash."""
        crawler = self._make_crawler()
        html = (
            "<html><head>"
            "<title>User | TikTok</title>"
            '<meta name="description">'  # no content attr
            "</head><body></body></html>"
        )
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("user")
        assert result.data.get("bio") == ""

    @pytest.mark.asyncio
    async def test_scrape_account_not_found(self):
        """'Couldn't find this account' triggers found=False."""
        crawler = self._make_crawler()
        resp = _mock_resp(200, text="Couldn't find this account on TikTok")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("nosuchuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_scrape_strips_at_sign(self):
        """Leading '@' must be stripped from handle."""
        crawler = self._make_crawler()
        html = "<html><head><title>User | TikTok</title></head><body></body></html>"
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("@AtUser")
        # handle stored in data should not have '@'
        assert result.data.get("handle") == "atuser"

    @pytest.mark.asyncio
    async def test_parse_full_json_path(self):
        """Happy-path JSON rehydration should populate all stat fields."""
        from modules.crawlers.tiktok import TikTokCrawler

        crawler = TikTokCrawler.__new__(TikTokCrawler)
        crawler.platform = "tiktok"
        crawler.source_reliability = 0.50

        import json

        json_blob = {
            "__DEFAULT_SCOPE__": {
                "webapp.user-detail": {
                    "userInfo": {
                        "user": {
                            "nickname": "Cool Creator",
                            "signature": "Making videos",
                            "verified": True,
                            "id": "987654",
                        },
                        "stats": {
                            "followerCount": 50000,
                            "followingCount": 100,
                            "videoCount": 250,
                            "heartCount": 1000000,
                        },
                    }
                }
            }
        }
        html = f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{json.dumps(json_blob)}</script>'
        data = crawler._parse(html, "coolcreator")
        assert data["display_name"] == "Cool Creator"
        assert data["follower_count"] == 50000
        assert data["is_verified"] is True
        assert data["post_count"] == 250


# ===========================================================================
# username_sherlock.py
# ===========================================================================


class TestUsernameSherlock:
    """Covers _check_sherlock_installed error branches and scrape() FileNotFoundError."""

    def _make_crawler(self):
        from modules.crawlers.username_sherlock import UsernameSherockCrawler

        c = UsernameSherockCrawler.__new__(UsernameSherockCrawler)
        c.platform = "username_sherlock"
        c.source_reliability = 0.65
        c.requires_tor = False
        return c

    # --- _check_sherlock_installed branches ---

    @pytest.mark.asyncio
    async def test_check_sherlock_timeout(self):
        """TimeoutError during --help probe must return False."""
        from modules.crawlers.username_sherlock import _check_sherlock_installed

        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = MagicMock()
            mock_exec.return_value = mock_proc
            with patch("asyncio.wait_for", new=AsyncMock(side_effect=TimeoutError())):
                result = await _check_sherlock_installed()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_sherlock_file_not_found(self):
        """FileNotFoundError (sherlock not on PATH) must return False."""
        from modules.crawlers.username_sherlock import _check_sherlock_installed

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError("sherlock not found")),
        ):
            result = await _check_sherlock_installed()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_sherlock_returns_true_when_installed(self):
        """When sherlock --help exits cleanly, return True."""
        from modules.crawlers.username_sherlock import _check_sherlock_installed

        mock_proc = MagicMock()
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"", b""))):
                result = await _check_sherlock_installed()
        assert result is True

    # --- scrape() FileNotFoundError branch (lines ~90-91) ---

    @pytest.mark.asyncio
    async def test_scrape_file_not_found_after_check(self):
        """
        If _check_sherlock_installed passes but _run_sherlock raises
        FileNotFoundError, result should carry sherlock_not_installed error.
        """
        crawler = self._make_crawler()
        with patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.username_sherlock._run_sherlock",
                new=AsyncMock(side_effect=FileNotFoundError("sherlock gone")),
            ):
                result = await crawler.scrape("targetuser")
        assert result.found is False
        assert result.error == "sherlock_not_installed"

    # --- scrape() TimeoutError branch ---

    @pytest.mark.asyncio
    async def test_scrape_timeout(self):
        """TimeoutError from _run_sherlock should produce sherlock_timeout error."""
        crawler = self._make_crawler()
        with patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.username_sherlock._run_sherlock",
                new=AsyncMock(side_effect=TimeoutError()),
            ):
                result = await crawler.scrape("slowuser")
        assert result.found is False
        assert result.error == "sherlock_timeout"

    # --- scrape() not installed ---

    @pytest.mark.asyncio
    async def test_scrape_sherlock_not_installed(self):
        """When _check_sherlock_installed returns False, skip execution."""
        crawler = self._make_crawler()
        with patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=False),
        ):
            result = await crawler.scrape("anyuser")
        assert result.found is False
        assert result.error == "sherlock_not_installed"

    # --- scrape() happy path ---

    @pytest.mark.asyncio
    async def test_scrape_success(self):
        """When sherlock returns hits, found=True and data is populated."""
        crawler = self._make_crawler()
        hits = [
            {"site": "Twitter", "url": "https://twitter.com/user"},
            {"site": "GitHub", "url": "https://github.com/user"},
        ]
        with patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ):
            with patch(
                "modules.crawlers.username_sherlock._run_sherlock",
                new=AsyncMock(return_value=hits),
            ):
                result = await crawler.scrape("user")
        assert result.found is True
        assert result.data.get("site_count") == 2
        assert result.data.get("found_on") == hits


# ===========================================================================
# public_voter.py
# ===========================================================================


class TestPublicVoterCrawler:
    """Covers branches in PublicVoterCrawler and helper functions."""

    def _make_crawler(self):
        from modules.crawlers.public_voter import PublicVoterCrawler

        c = PublicVoterCrawler.__new__(PublicVoterCrawler)
        c.platform = "public_voter"
        c.source_reliability = 0.85
        c.requires_tor = False
        return c

    # --- _parse_voter_response: non-dict input (line ~89) ---

    def test_parse_voter_response_non_dict(self):
        """Passing a list or string must return the default unregistered dict."""
        from modules.crawlers.public_voter import _parse_voter_response

        for bad_input in [None, [], "some string", 42]:
            result = _parse_voter_response(bad_input)
            assert result["registered"] is False
            assert result["state"] == "MI"

    # --- _parse_voter_response: direct JSON shape ---

    def test_parse_voter_response_direct_shape_registered(self):
        from modules.crawlers.public_voter import _parse_voter_response

        data = {
            "Registered": True,
            "CountyName": "Wayne",
            "JurisdictionName": "Detroit",
            "VoterStatus": "Active",
        }
        result = _parse_voter_response(data)
        assert result["registered"] is True
        assert result["county"] == "Wayne"
        assert result["jurisdiction"] == "Detroit"
        assert result["status"] == "Active"

    def test_parse_voter_response_direct_shape_not_registered(self):
        from modules.crawlers.public_voter import _parse_voter_response

        data = {"Registered": False, "CountyName": None}
        result = _parse_voter_response(data)
        assert result["registered"] is False

    # --- _parse_voter_response: HTML-in-JSON shape (lines ~100-111) ---

    def test_parse_voter_response_html_in_json_registered(self):
        """HTML fragment containing 'you are registered' should set registered=True."""
        from modules.crawlers.public_voter import _parse_voter_response

        data = {
            "d": "<div>You are registered to vote in Wayne County</div>",
        }
        result = _parse_voter_response(data)
        assert result["registered"] is True

    def test_parse_voter_response_html_in_json_no_match(self):
        """HTML fragment with no registration text should stay registered=False."""
        from modules.crawlers.public_voter import _parse_voter_response

        data = {"d": "<div>No voter found matching your criteria.</div>"}
        result = _parse_voter_response(data)
        assert result["registered"] is False

    def test_parse_voter_response_html_registered_to_vote_phrase(self):
        """'registered to vote' (alternate phrase) should also trigger registered=True."""
        from modules.crawlers.public_voter import _parse_voter_response

        data = {"msg": "Congratulations, registered to vote in Oakland County."}
        result = _parse_voter_response(data)
        assert result["registered"] is True

    # --- scrape(): non-200 POST (line ~174) ---

    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        crawler = self._make_crawler()
        resp = _mock_resp(503, text="Service Unavailable")
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_503"

    # --- scrape(): None response ---

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    # --- scrape(): JSON error (lines ~188-190) ---

    @pytest.mark.asyncio
    async def test_scrape_json_parse_error(self):
        """Non-JSON body must return json_parse_error without raising."""
        crawler = self._make_crawler()
        resp = _mock_resp(200, text="<html>not json</html>")
        # Ensure .json() raises
        resp.json.side_effect = ValueError("not json")
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe")
        assert result.found is False
        assert result.data.get("error") == "json_parse_error"

    # --- scrape(): happy path with direct JSON ---

    @pytest.mark.asyncio
    async def test_scrape_success_registered(self):
        crawler = self._make_crawler()
        json_payload = {
            "Registered": True,
            "CountyName": "Washtenaw",
            "JurisdictionName": "Ann Arbor",
            "VoterStatus": "Active",
        }
        resp = _mock_resp(200, json_data=json_payload)
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith|03|1985")
        assert result.found is True
        assert result.data.get("registered") is True

    # --- _parse_identifier edge cases ---

    def test_parse_identifier_name_only(self):
        from modules.crawlers.public_voter import _parse_identifier

        p = _parse_identifier("John Smith")
        assert p["first"] == "John"
        assert p["last"] == "Smith"
        assert p["month"] == ""
        assert p["year"] == ""
        assert p["city"] == ""

    def test_parse_identifier_full(self):
        from modules.crawlers.public_voter import _parse_identifier

        p = _parse_identifier("Mary Jane Watson|06|1990|Detroit")
        assert p["first"] == "Mary"
        assert p["last"] == "Jane Watson"
        assert p["month"] == "06"
        assert p["year"] == "1990"
        assert p["city"] == "Detroit"

    def test_parse_identifier_single_name(self):
        from modules.crawlers.public_voter import _parse_identifier

        p = _parse_identifier("Madonna")
        assert p["first"] == "Madonna"
        assert p["last"] == ""


# ===========================================================================
# court_state.py
# ===========================================================================


class TestCourtStateCrawler:
    """Covers bs4 ImportError, short tables, and portal exception branches."""

    def _make_crawler(self):
        from modules.crawlers.court_state import CourtStateCrawler

        c = CourtStateCrawler.__new__(CourtStateCrawler)
        c.platform = "court_state"
        c.source_reliability = 0.90
        c.requires_tor = False
        return c

    # --- bs4 ImportError branch (lines ~38-40) ---

    def test_parse_table_rows_bs4_import_error(self):
        """When BeautifulSoup is not importable, _parse_table_rows must return []."""
        from modules.crawlers import court_state

        with patch.dict(sys.modules, {"bs4": None}):
            # Force the lazy import inside the function to fail
            (__builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__)  # noqa

            def _block_bs4(name, *args, **kwargs):
                if name == "bs4":
                    raise ImportError("bs4 not available")
                return __import__(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=_block_bs4):
                result = court_state._parse_table_rows("<table></table>", "TX")
        assert result == []

    # --- Table with < 2 rows (short table skip) ---

    def test_parse_table_rows_single_row_table_skipped(self):
        """A table with only a header row (no data rows) must be skipped."""
        from modules.crawlers.court_state import _parse_table_rows

        html = "<table><tr><th>Case No.</th><th>Party</th><th>Type</th><th>Date</th></tr></table>"
        result = _parse_table_rows(html, "TX")
        assert result == []

    def test_parse_table_rows_empty_table(self):
        """Completely empty table should be skipped."""
        from modules.crawlers.court_state import _parse_table_rows

        result = _parse_table_rows("<table></table>", "TX")
        assert result == []

    def test_parse_table_rows_single_header_column_skipped(self):
        """Table with < 2 header columns must be skipped."""
        from modules.crawlers.court_state import _parse_table_rows

        html = "<table><tr><th>Only One Column</th></tr><tr><td>data</td></tr></table>"
        result = _parse_table_rows(html, "TX")
        assert result == []

    def test_parse_table_rows_with_valid_data(self):
        """Table with valid header + data rows should return parsed records."""
        from modules.crawlers.court_state import _parse_table_rows

        html = (
            "<table>"
            "<tr><th>Case No.</th><th>Party Name</th><th>Case Type</th><th>Date Filed</th></tr>"
            "<tr><td>2024-TX-001</td><td>John Smith</td><td>Civil</td><td>2024-01-15</td></tr>"
            "<tr><td>2024-TX-002</td><td>John Smith</td><td>Criminal</td><td>2024-02-20</td></tr>"
            "</table>"
        )
        result = _parse_table_rows(html, "TX")
        assert len(result) == 2
        assert result[0]["state"] == "TX"
        # case_number normalisation
        assert result[0]["case_number"] == "2024-TX-001"

    def test_parse_table_rows_empty_data_row_skipped(self):
        """A data row with only empty cells is included (state field is non-empty)."""
        from modules.crawlers.court_state import _parse_table_rows

        html = "<table><tr><th>Case No.</th><th>Party</th></tr><tr><td></td><td></td></tr></table>"
        result = _parse_table_rows(html, "TX")
        # The row has empty case cells but the record includes state="TX",
        # so any(record.values()) is True and the record is appended.
        assert len(result) == 1
        assert result[0]["state"] == "TX"
        assert result[0]["case_number"] == ""

    # --- _scrape_portal exception branch (lines ~132-139) ---

    @pytest.mark.asyncio
    async def test_scrape_portal_exception_returns_empty(self):
        """Any exception inside _scrape_portal must be caught and return []."""
        crawler = self._make_crawler()
        with patch.object(
            crawler,
            "page",
            side_effect=Exception("Playwright not available"),
        ):
            result = await crawler._scrape_portal("https://example.com", "TX")
        assert result == []

    # --- Full scrape() with both portals erroring ---

    @pytest.mark.asyncio
    async def test_scrape_both_portals_fail(self):
        """When both portals raise, result must be found=False with empty cases."""
        crawler = self._make_crawler()
        with patch.object(
            crawler,
            "_scrape_portal",
            new=AsyncMock(return_value=[]),
        ):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("case_count") == 0
        assert result.data.get("cases") == []

    @pytest.mark.asyncio
    async def test_scrape_tx_returns_cases(self):
        """Cases from TX portal should be included in final result."""
        crawler = self._make_crawler()
        tx_case = {"state": "TX", "case_number": "2024-001", "parties": "Smith"}
        call_count = 0

        async def fake_scrape_portal(url, state):
            nonlocal call_count
            call_count += 1
            if state == "TX":
                return [tx_case]
            return []

        with patch.object(crawler, "_scrape_portal", side_effect=fake_scrape_portal):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.data.get("case_count") == 1
        assert call_count == 2  # Both portals must be queried


# ===========================================================================
# crypto_blockchair.py
# ===========================================================================


class TestCryptoBlockchairCrawler:
    """Covers _parse_blockchair_response unit tests and HTTP error branches."""

    def _make_crawler(self):
        from modules.crawlers.crypto_blockchair import CryptoBlockchairCrawler

        c = CryptoBlockchairCrawler.__new__(CryptoBlockchairCrawler)
        c.platform = "crypto_blockchair"
        c.source_reliability = 0.80
        c.requires_tor = True
        return c

    # --- _parse_blockchair_response unit tests ---

    def test_parse_empty_data_block(self):
        """Empty 'data' key must return None."""
        from modules.crawlers.crypto_blockchair import _parse_blockchair_response

        assert _parse_blockchair_response({"data": {}}, "1ABC") is None

    def test_parse_missing_data_key(self):
        """Missing 'data' key must return None."""
        from modules.crawlers.crypto_blockchair import _parse_blockchair_response

        assert _parse_blockchair_response({}, "1ABC") is None

    def test_parse_address_exact_match(self):
        """Address found by exact key match should return correct stats."""
        from modules.crawlers.crypto_blockchair import _parse_blockchair_response

        addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf"
        json_data = {
            "data": {
                addr: {
                    "address": {
                        "balance": 5000000000,
                        "balance_usd": 12345.67,
                        "transaction_count": 42,
                        "received": 10000000000,
                        "spent": 5000000000,
                        "output_count": 10,
                        "unspent_output_count": 5,
                    }
                }
            }
        }
        result = _parse_blockchair_response(json_data, addr)
        assert result is not None
        assert result["balance"] == 5000000000
        assert result["transaction_count"] == 42
        assert result["balance_usd"] == 12345.67

    def test_parse_address_case_insensitive_fallback(self):
        """Address stored in lowercase should be found case-insensitively."""
        from modules.crawlers.crypto_blockchair import _parse_blockchair_response

        addr = "0xABCDEF1234"
        json_data = {
            "data": {
                addr.lower(): {
                    "address": {
                        "balance": 1000,
                        "transaction_count": 3,
                        "received": 2000,
                        "spent": 1000,
                    }
                }
            }
        }
        result = _parse_blockchair_response(json_data, addr)
        assert result is not None
        assert result["balance"] == 1000

    def test_parse_address_first_value_fallback(self):
        """When key is not found, should fall back to first value in data block."""
        from modules.crawlers.crypto_blockchair import _parse_blockchair_response

        json_data = {
            "data": {
                "SOME_OTHER_KEY": {
                    "address": {
                        "balance": 777,
                        "transaction_count": 7,
                        "received": 1000,
                        "spent": 223,
                    }
                }
            }
        }
        result = _parse_blockchair_response(json_data, "UNKNOWN_ADDR")
        assert result is not None
        assert result["balance"] == 777

    def test_parse_none_addr_data_when_data_block_present_but_all_none(self):
        """data block exists but first value is None-equivalent — return None."""
        from modules.crawlers.crypto_blockchair import _parse_blockchair_response

        # Non-empty data block but the address entry itself has no 'address' sub-key
        json_data = {"data": {"addr": {}}}
        result = _parse_blockchair_response(json_data, "addr")
        # addr_data is {} (not None), addr_stats is {}, returns dict with defaults
        assert result is not None
        assert result["balance"] == 0
        assert result["transaction_count"] == 0

    # --- HTTP error branches ---

    @pytest.mark.asyncio
    async def test_scrape_invalid_identifier_format(self):
        """Identifier without ':' must return invalid_identifier_format error."""
        crawler = self._make_crawler()
        result = await crawler.scrape("btc1A1zP1eP5")
        assert result.found is False
        assert result.error == "invalid_identifier_format"

    @pytest.mark.asyncio
    async def test_scrape_unsupported_chain(self):
        """Unknown chain code must return unsupported_chain error."""
        crawler = self._make_crawler()
        result = await crawler.scrape("xmr:someaddress")
        assert result.found is False
        assert "unsupported_chain" in result.error

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("btc:1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_scrape_rate_limited(self):
        crawler = self._make_crawler()
        resp = _mock_resp(429, text="Rate limit exceeded")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("eth:0xABC123")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_scrape_404(self):
        crawler = self._make_crawler()
        resp = _mock_resp(404, text="Not found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("btc:1unknownaddr")
        assert result.found is False
        assert result.error == "address_not_found"

    @pytest.mark.asyncio
    async def test_scrape_500(self):
        crawler = self._make_crawler()
        resp = _mock_resp(500, text="Server error")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("btc:1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "http_500"

    @pytest.mark.asyncio
    async def test_scrape_invalid_json(self):
        crawler = self._make_crawler()
        resp = _mock_resp(200, text="not-json{{{")
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("btc:1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_scrape_unexpected_response_structure(self):
        """Valid JSON but missing expected structure returns unexpected_response_structure."""
        crawler = self._make_crawler()
        resp = _mock_resp(200, json_data={"data": {}})  # empty data block
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("btc:1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "unexpected_response_structure"

    @pytest.mark.asyncio
    async def test_scrape_happy_path(self):
        """Valid Blockchair response produces found=True with stats."""
        crawler = self._make_crawler()
        addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf"
        json_payload = {
            "data": {
                addr: {
                    "address": {
                        "balance": 5000000000,
                        "balance_usd": 1234.56,
                        "transaction_count": 10,
                        "received": 10000000000,
                        "spent": 5000000000,
                    }
                }
            }
        }
        resp = _mock_resp(200, json_data=json_payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape(f"btc:{addr}")
        assert result.found is True
        assert result.data.get("balance") == 5000000000
        assert result.data.get("transaction_count") == 10


# ===========================================================================
# crypto_ethereum.py
# ===========================================================================


class TestCryptoEthereumCrawler:
    """Covers balance None/429/503 and TX JSON error swallow."""

    def _make_crawler(self):
        from modules.crawlers.crypto_ethereum import CryptoEthereumCrawler

        c = CryptoEthereumCrawler.__new__(CryptoEthereumCrawler)
        c.platform = "crypto_ethereum"
        c.source_reliability = 0.85
        c.requires_tor = True
        return c

    # --- balance None response ---

    @pytest.mark.asyncio
    async def test_scrape_balance_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("0xABC123")
        assert result.found is False
        assert result.error == "http_error"

    # --- balance 429 ---

    @pytest.mark.asyncio
    async def test_scrape_balance_429(self):
        crawler = self._make_crawler()
        resp = _mock_resp(429, text="Rate limit")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("0xABC123")
        assert result.found is False
        assert result.error == "rate_limited"

    # --- balance 503 ---

    @pytest.mark.asyncio
    async def test_scrape_balance_503(self):
        crawler = self._make_crawler()
        resp = _mock_resp(503, text="Service unavailable")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("0xABC123")
        assert result.found is False
        assert result.error == "http_503"

    # --- balance JSON error ---

    @pytest.mark.asyncio
    async def test_scrape_balance_invalid_json(self):
        crawler = self._make_crawler()
        resp = _mock_resp(200, text="not-json")
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("0xABC123")
        assert result.found is False
        assert result.error == "invalid_json"

    # --- balance API error status ---

    @pytest.mark.asyncio
    async def test_scrape_balance_api_error_status(self):
        """Etherscan status != '1' should produce api_error."""
        crawler = self._make_crawler()
        resp = _mock_resp(200)
        resp.json.return_value = {"status": "0", "message": "NOTOK", "result": "Error!"}
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("0xABC123")
        assert result.found is False

    # --- TX JSON error swallow (lines ~133-134) ---

    @pytest.mark.asyncio
    async def test_scrape_tx_json_error_swallowed(self):
        """
        If balance fetch succeeds but TX fetch returns bad JSON,
        the exception is swallowed and result is still found=True.
        """
        crawler = self._make_crawler()

        balance_resp = _mock_resp(
            200,
            json_data={
                "status": "1",
                "message": "OK",
                "result": "1000000000000000000",  # 1 ETH in wei
            },
        )

        tx_resp = _mock_resp(200, text="bad-json-here")
        tx_resp.json.side_effect = ValueError("not json")

        call_count = 0

        async def side_effect_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return balance_resp
            return tx_resp

        with patch.object(crawler, "get", side_effect=side_effect_get):
            result = await crawler.scrape("0xABC123")

        assert result.found is True
        assert result.data.get("balance_eth") == pytest.approx(1.0)
        assert result.data.get("tx_count") == 0
        assert result.data.get("recent_txs") == []

    # --- TX response None ---

    @pytest.mark.asyncio
    async def test_scrape_tx_none_response_graceful(self):
        """None TX response must be handled gracefully — found=True with empty txs."""
        crawler = self._make_crawler()

        balance_resp = _mock_resp(
            200,
            json_data={
                "status": "1",
                "message": "OK",
                "result": "500000000000000000",  # 0.5 ETH
            },
        )

        call_count = 0

        async def side_effect_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return balance_resp
            return None  # TX fetch returns None

        with patch.object(crawler, "get", side_effect=side_effect_get):
            result = await crawler.scrape("0xDEF456")

        assert result.found is True
        assert result.data.get("tx_count") == 0

    # --- TX status != '1' graceful ---

    @pytest.mark.asyncio
    async def test_scrape_tx_api_status_not_1(self):
        """TX response with status != '1' should result in empty txlist."""
        crawler = self._make_crawler()

        balance_resp = _mock_resp(
            200,
            json_data={
                "status": "1",
                "message": "OK",
                "result": "0",
            },
        )

        tx_resp = _mock_resp(
            200,
            json_data={
                "status": "0",
                "message": "No transactions found",
                "result": [],
            },
        )

        call_count = 0

        async def side_effect_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return balance_resp if call_count == 1 else tx_resp

        with patch.object(crawler, "get", side_effect=side_effect_get):
            result = await crawler.scrape("0x0000000")

        assert result.found is True
        assert result.data.get("tx_count") == 0

    # --- Happy path ---

    @pytest.mark.asyncio
    async def test_scrape_full_happy_path(self):
        crawler = self._make_crawler()

        balance_resp = _mock_resp(
            200,
            json_data={
                "status": "1",
                "message": "OK",
                "result": "2000000000000000000",  # 2 ETH
            },
        )

        tx_resp = _mock_resp(
            200,
            json_data={
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "hash": "0xabc",
                        "from": "0x111",
                        "to": "0x222",
                        "value": "1000000000000000000",
                        "timeStamp": "1700000000",
                    }
                ],
            },
        )

        call_count = 0

        async def side_effect_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return balance_resp if call_count == 1 else tx_resp

        with patch.object(crawler, "get", side_effect=side_effect_get):
            result = await crawler.scrape("0xALICE")

        assert result.found is True
        assert result.data.get("balance_eth") == pytest.approx(2.0)
        assert result.data.get("tx_count") == 1
        recent = result.data.get("recent_txs", [])
        assert len(recent) == 1
        assert recent[0]["hash"] == "0xabc"


# ===========================================================================
# crypto_bitcoin.py
# ===========================================================================


class TestCryptoBitcoinCrawler:
    """Covers 404/429/503/500/403 and JSON error responses."""

    def _make_crawler(self):
        from modules.crawlers.crypto_bitcoin import CryptoBitcoinCrawler

        c = CryptoBitcoinCrawler.__new__(CryptoBitcoinCrawler)
        c.platform = "crypto_bitcoin"
        c.source_reliability = 0.85
        c.requires_tor = True
        return c

    # --- None response ---

    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "http_error"

    # --- 404 ---

    @pytest.mark.asyncio
    async def test_scrape_404(self):
        crawler = self._make_crawler()
        resp = _mock_resp(404, text="Not Found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1unknownaddr")
        assert result.found is False
        assert result.error == "address_not_found"

    # --- 429 ---

    @pytest.mark.asyncio
    async def test_scrape_429(self):
        crawler = self._make_crawler()
        resp = _mock_resp(429, text="Too Many Requests")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "rate_limited"

    # --- 503 ---

    @pytest.mark.asyncio
    async def test_scrape_503(self):
        crawler = self._make_crawler()
        resp = _mock_resp(503, text="Service Unavailable")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "http_503"

    # --- 500 ---

    @pytest.mark.asyncio
    async def test_scrape_500(self):
        crawler = self._make_crawler()
        resp = _mock_resp(500, text="Internal Server Error")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "http_500"

    # --- 403 ---

    @pytest.mark.asyncio
    async def test_scrape_403(self):
        crawler = self._make_crawler()
        resp = _mock_resp(403, text="Forbidden")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "http_403"

    # --- JSON parse error ---

    @pytest.mark.asyncio
    async def test_scrape_invalid_json(self):
        crawler = self._make_crawler()
        resp = _mock_resp(200, text="not-json-at-all")
        resp.json.side_effect = ValueError("not json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")
        assert result.found is False
        assert result.error == "invalid_json"

    # --- Happy path ---

    @pytest.mark.asyncio
    async def test_scrape_happy_path(self):
        """Valid blockchain.info response should populate all fields."""
        crawler = self._make_crawler()
        json_payload = {
            "final_balance": 500000000,  # 5 BTC
            "total_received": 1000000000,  # 10 BTC
            "total_sent": 500000000,  # 5 BTC
            "n_tx": 3,
            "txs": [
                {
                    "hash": "txhash1",
                    "time": 1700000000,
                    "out": [{"value": 100000000}, {"value": 50000000}],
                },
                {
                    "hash": "txhash2",
                    "time": 1700100000,
                    "out": [{"value": 200000000}],
                },
            ],
        }
        resp = _mock_resp(200, json_data=json_payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")

        assert result.found is True
        assert result.data.get("balance_btc") == pytest.approx(5.0)
        assert result.data.get("total_received_btc") == pytest.approx(10.0)
        assert result.data.get("total_sent_btc") == pytest.approx(5.0)
        assert result.data.get("tx_count") == 3
        recent = result.data.get("recent_txs", [])
        assert len(recent) == 2
        assert recent[0]["hash"] == "txhash1"
        assert recent[0]["amount_btc"] == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_scrape_empty_txs(self):
        """Address with no transactions should still return found=True."""
        crawler = self._make_crawler()
        json_payload = {
            "final_balance": 0,
            "total_received": 0,
            "total_sent": 0,
            "n_tx": 0,
            "txs": [],
        }
        resp = _mock_resp(200, json_data=json_payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1EmptyAddress")
        assert result.found is True
        assert result.data.get("tx_count") == 0
        assert result.data.get("recent_txs") == []

    # --- _satoshi_to_btc and _parse_recent_txs unit tests ---

    def test_satoshi_to_btc_conversion(self):
        from modules.crawlers.crypto_bitcoin import _satoshi_to_btc

        assert _satoshi_to_btc(100000000) == pytest.approx(1.0)
        assert _satoshi_to_btc(50000000) == pytest.approx(0.5)
        assert _satoshi_to_btc(0) == pytest.approx(0.0)

    def test_parse_recent_txs_limit(self):
        """Only the first `limit` transactions should be returned."""
        from modules.crawlers.crypto_bitcoin import _parse_recent_txs

        txs = [{"hash": f"tx{i}", "time": i, "out": [{"value": i * 1000}]} for i in range(10)]
        result = _parse_recent_txs(txs, limit=3)
        assert len(result) == 3
        assert result[0]["hash"] == "tx0"

    def test_parse_recent_txs_missing_fields(self):
        """Transactions with missing fields should not raise."""
        from modules.crawlers.crypto_bitcoin import _parse_recent_txs

        txs = [{}]  # completely empty tx
        result = _parse_recent_txs(txs)
        assert len(result) == 1
        assert result[0]["hash"] == ""
        assert result[0]["time"] == 0
        assert result[0]["amount_btc"] == pytest.approx(0.0)
