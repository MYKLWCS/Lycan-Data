"""
test_username_tools_wave4.py — Branch-coverage gap tests (wave 4).

Crawlers covered:
  username_maigret  — lines 29, 58-125
  phone_phoneinfoga — lines 28-41, 58-116

Each test mocks subprocess/asyncio.to_thread at the module level so no
external binaries are needed.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# username_maigret.py
# ===========================================================================


class TestMaigretCrawler:
    """Covers lines 29, 58-125 of modules/crawlers/username_maigret.py."""

    def _make_crawler(self):
        from modules.crawlers.username_maigret import MaigretCrawler

        return MaigretCrawler()

    # -----------------------------------------------------------------------
    # Line 60-67: maigret not on PATH → not_installed error
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_maigret_not_installed_returns_error(self):
        crawler = self._make_crawler()
        with patch("shutil.which", return_value=None):
            result = await crawler.scrape("testuser")
        assert result.found is False
        assert result.error == "maigret_not_installed"

    # -----------------------------------------------------------------------
    # Lines 69-72: asyncio.to_thread called; normal path, no report file
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_report_file_returns_no_output(self):
        """Maigret runs but produces no JSON file → no_output error."""
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/maigret"),
            patch("asyncio.to_thread", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("testuser")
        assert result.found is False
        assert result.error == "no_output"

    # -----------------------------------------------------------------------
    # Lines 73-80: TimeoutExpired during to_thread
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_error(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/maigret"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(side_effect=subprocess.TimeoutExpired("maigret", 300)),
            ),
        ):
            result = await crawler.scrape("testuser")
        assert result.found is False
        assert result.error == "maigret_timeout"

    # -----------------------------------------------------------------------
    # Lines 81-88: FileNotFoundError during to_thread
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_file_not_found_returns_not_installed(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/maigret"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(side_effect=FileNotFoundError("maigret not found")),
            ),
        ):
            result = await crawler.scrape("testuser")
        assert result.found is False
        assert result.error == "maigret_not_installed"

    # -----------------------------------------------------------------------
    # Lines 100-109: Report file exists but contains invalid JSON
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_invalid_json_report_returns_error(self):
        crawler = self._make_crawler()

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "testuser.json"
            report_path.write_text("NOT VALID JSON {{{{")

            async def _fake_to_thread(fn, *args, **kwargs):
                # Do nothing — file is already written above
                return None

            with (
                patch("shutil.which", return_value="/usr/bin/maigret"),
                patch("asyncio.to_thread", new=_fake_to_thread),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=MagicMock(
                        __enter__=MagicMock(return_value=tmpdir),
                        __exit__=MagicMock(return_value=False),
                    ),
                ),
            ):
                result = await crawler.scrape("testuser")

        assert result.found is False
        assert result.error == "invalid_json"

    # -----------------------------------------------------------------------
    # Lines 111-131: Valid JSON with Claimed and non-Claimed sites
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_valid_json_returns_claimed_sites(self):
        crawler = self._make_crawler()

        maigret_output = {
            "GitHub": {"status": {"status": "Claimed"}, "url": "https://github.com/testuser"},
            "Twitter": {"status": {"status": "Claimed"}, "url": "https://twitter.com/testuser"},
            "Reddit": {"status": {"status": "Not Found"}, "url": ""},
            "Instagram": {"status": {}, "url": ""},  # missing status key
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "testuser.json"
            report_path.write_text(json.dumps(maigret_output))

            async def _fake_to_thread(fn, *args, **kwargs):
                return None

            with (
                patch("shutil.which", return_value="/usr/bin/maigret"),
                patch("asyncio.to_thread", new=_fake_to_thread),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=MagicMock(
                        __enter__=MagicMock(return_value=tmpdir),
                        __exit__=MagicMock(return_value=False),
                    ),
                ),
            ):
                result = await crawler.scrape("testuser")

        assert result.found is True
        assert result.data["site_count"] == 2
        sites = result.data["sites_found"]
        site_names = [s["site"] for s in sites]
        assert "GitHub" in site_names
        assert "Twitter" in site_names
        assert "Reddit" not in site_names

    # -----------------------------------------------------------------------
    # Empty Claimed list — found=True with site_count=0
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_claimed_sites_returns_found_true_empty(self):
        crawler = self._make_crawler()

        maigret_output = {
            "Reddit": {"status": {"status": "Not Found"}, "url": ""},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "testuser.json"
            report_path.write_text(json.dumps(maigret_output))

            async def _fake_to_thread(fn, *args, **kwargs):
                return None

            with (
                patch("shutil.which", return_value="/usr/bin/maigret"),
                patch("asyncio.to_thread", new=_fake_to_thread),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=MagicMock(
                        __enter__=MagicMock(return_value=tmpdir),
                        __exit__=MagicMock(return_value=False),
                    ),
                ),
            ):
                result = await crawler.scrape("testuser")

        assert result.found is True
        assert result.data["site_count"] == 0

    # -----------------------------------------------------------------------
    # Line 29: _run_maigret_sync calls subprocess.run with correct args
    # -----------------------------------------------------------------------

    def test_run_maigret_sync_calls_subprocess(self):
        from modules.crawlers.username_maigret import _run_maigret_sync

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            _run_maigret_sync("johnsmith", "/tmp/johnsmith.json")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "maigret"
        assert call_args[1] == "johnsmith"
        assert "/tmp/johnsmith.json" in call_args
        assert "--json" in call_args

    def test_run_maigret_sync_timeout_propagates(self):
        """TimeoutExpired is NOT caught in _run_maigret_sync — it propagates up."""
        from modules.crawlers.username_maigret import _run_maigret_sync

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("maigret", 300),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _run_maigret_sync("testuser", "/tmp/x.json")

    def test_run_maigret_sync_file_not_found_propagates(self):
        """FileNotFoundError propagates from _run_maigret_sync."""
        from modules.crawlers.username_maigret import _run_maigret_sync

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                _run_maigret_sync("testuser", "/tmp/x.json")


# ===========================================================================
# phone_phoneinfoga.py
# ===========================================================================


class TestPhoneInfogaCrawler:
    """Covers lines 28-41, 58-116 of modules/crawlers/phone_phoneinfoga.py."""

    def _make_crawler(self):
        from modules.crawlers.phone_phoneinfoga import PhoneInfogaCrawler

        return PhoneInfogaCrawler()

    # -----------------------------------------------------------------------
    # Lines 28-41: _run_phoneinfoga_sync — subprocess.run invocation
    # -----------------------------------------------------------------------

    def test_run_phoneinfoga_sync_calls_subprocess(self):
        from modules.crawlers.phone_phoneinfoga import _run_phoneinfoga_sync

        mock_result = MagicMock(returncode=0, stdout=b'{"carrier": "T-Mobile"}', stderr=b"")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            output = _run_phoneinfoga_sync("+15550001111")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "phoneinfoga"
        assert "scan" in call_args
        assert "+15550001111" in call_args
        assert output == b'{"carrier": "T-Mobile"}'

    def test_run_phoneinfoga_sync_timeout_propagates(self):
        from modules.crawlers.phone_phoneinfoga import _run_phoneinfoga_sync

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("phoneinfoga", 120),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _run_phoneinfoga_sync("+15550001111")

    def test_run_phoneinfoga_sync_file_not_found_propagates(self):
        from modules.crawlers.phone_phoneinfoga import _run_phoneinfoga_sync

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                _run_phoneinfoga_sync("+15550001111")

    # -----------------------------------------------------------------------
    # Lines 60-67: phoneinfoga not on PATH → not_installed error
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_phoneinfoga_not_installed_returns_error(self):
        crawler = self._make_crawler()
        with patch("shutil.which", return_value=None):
            result = await crawler.scrape("+15550001111")
        assert result.found is False
        assert result.error == "phoneinfoga_not_installed"

    # -----------------------------------------------------------------------
    # Lines 71-78: TimeoutExpired during to_thread
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_error(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(side_effect=subprocess.TimeoutExpired("phoneinfoga", 120)),
            ),
        ):
            result = await crawler.scrape("+15550001111")
        assert result.found is False
        assert result.error == "phoneinfoga_timeout"

    # -----------------------------------------------------------------------
    # Lines 79-86: FileNotFoundError during to_thread
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_file_not_found_returns_not_installed(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(side_effect=FileNotFoundError),
            ),
        ):
            result = await crawler.scrape("+15550001111")
        assert result.found is False
        assert result.error == "phoneinfoga_not_installed"

    # -----------------------------------------------------------------------
    # Lines 88-95: empty stdout → no_output error
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_stdout_returns_no_output(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch("asyncio.to_thread", new=AsyncMock(return_value=b"")),
        ):
            result = await crawler.scrape("+15550001111")
        assert result.found is False
        assert result.error == "no_output"

    # -----------------------------------------------------------------------
    # Lines 97-106: invalid JSON stdout → invalid_json error
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch("asyncio.to_thread", new=AsyncMock(return_value=b"NOTJSON{{{")),
        ):
            result = await crawler.scrape("+15550001111")
        assert result.found is False
        assert result.error == "invalid_json"

    # -----------------------------------------------------------------------
    # Lines 108-126: valid dict JSON — normalise top-level fields
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dict_json_returns_found_with_fields(self):
        crawler = self._make_crawler()
        payload = {
            "carrier": "T-Mobile",
            "line_type": "mobile",
            "country": "US",
            "local": "5550001111",
            "international": "+15550001111",
        }
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=json.dumps(payload).encode()),
            ),
        ):
            result = await crawler.scrape("+15550001111")
        assert result.found is True
        assert result.data["carrier"] == "T-Mobile"
        assert result.data["line_type"] == "mobile"
        assert result.data["country"] == "US"

    # -----------------------------------------------------------------------
    # Capitalised keys variant (Carrier, LineType, etc.)
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_capitalised_keys_fallback(self):
        crawler = self._make_crawler()
        payload = {
            "Carrier": "Verizon",
            "LineType": "landline",
            "Country": "US",
            "Local": "5550009999",
            "International": "+15550009999",
        }
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=json.dumps(payload).encode()),
            ),
        ):
            result = await crawler.scrape("+15550009999")
        assert result.found is True
        assert result.data["carrier"] == "Verizon"
        assert result.data["line_type"] == "landline"

    # -----------------------------------------------------------------------
    # Lines 113-114: list JSON — take first element
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_json_uses_first_element(self):
        crawler = self._make_crawler()
        payload = [
            {"carrier": "AT&T", "line_type": "mobile", "country": "US"},
            {"carrier": "Other", "line_type": "landline", "country": "CA"},
        ]
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=json.dumps(payload).encode()),
            ),
        ):
            result = await crawler.scrape("+15550002222")
        assert result.found is True
        assert result.data["carrier"] == "AT&T"

    # -----------------------------------------------------------------------
    # Empty list JSON — result_data is empty dict, found=True
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_list_json_returns_found_with_empty_data(self):
        crawler = self._make_crawler()
        payload: list = []
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=json.dumps(payload).encode()),
            ),
        ):
            result = await crawler.scrape("+15550003333")
        assert result.found is True
        assert result.data["carrier"] is None

    # -----------------------------------------------------------------------
    # Non-dict, non-list JSON (e.g. a plain string) — result_data stays {}
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_scalar_json_returns_found_with_none_fields(self):
        crawler = self._make_crawler()
        with (
            patch("shutil.which", return_value="/usr/bin/phoneinfoga"),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=b'"just a string"'),
            ),
        ):
            result = await crawler.scrape("+15550004444")
        assert result.found is True
        assert result.data["carrier"] is None
