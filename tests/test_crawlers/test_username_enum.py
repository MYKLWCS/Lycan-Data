"""
Tests for username enumeration crawler:
  - UsernameSherlockCrawler (username_sherlock) — 10 tests
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.username_sherlock  # noqa: F401 — trigger @register
from modules.crawlers.registry import is_registered
from modules.crawlers.username_sherlock import UsernameSherlockCrawler, _run_sherlock

# ---------------------------------------------------------------------------
# Test 1: sherlock found results — correct parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sherlock_found_results():
    """Sherlock output with matches is parsed into found_on list."""
    crawler = UsernameSherlockCrawler()

    async def fake_run(username):
        return [
            {"site": "Twitter", "url": "https://twitter.com/johndoe"},
            {"site": "GitHub", "url": "https://github.com/johndoe"},
        ]

    with (
        patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.username_sherlock._run_sherlock", new=AsyncMock(side_effect=fake_run)
        ),
    ):
        result = await crawler.scrape("johndoe")

    assert result.found is True
    assert result.platform == "username_sherlock"
    assert len(result.data["found_on"]) == 2
    assert result.data["found_on"][0] == {"site": "Twitter", "url": "https://twitter.com/johndoe"}


# ---------------------------------------------------------------------------
# Test 2: sherlock no results → found=True, found_on=[]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sherlock_no_results():
    """Sherlock finds no accounts — result is still found=True with empty list."""
    crawler = UsernameSherlockCrawler()

    async def fake_run(username):
        return []

    with (
        patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.username_sherlock._run_sherlock", new=AsyncMock(side_effect=fake_run)
        ),
    ):
        result = await crawler.scrape("xyzxyzxyz_nobody")

    assert result.found is True
    assert result.data["found_on"] == []
    assert result.data["site_count"] == 0


# ---------------------------------------------------------------------------
# Test 3: sherlock timeout → CrawlerResult found=False, error message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sherlock_timeout():
    """Subprocess timeout returns found=False with sherlock_timeout error."""
    crawler = UsernameSherlockCrawler()

    async def timeout_run(username):
        raise TimeoutError()

    with (
        patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.username_sherlock._run_sherlock",
            new=AsyncMock(side_effect=timeout_run),
        ),
    ):
        result = await crawler.scrape("someuser")

    assert result.found is False
    assert result.error == "sherlock_timeout"


# ---------------------------------------------------------------------------
# Test 4: sherlock not installed (FileNotFoundError) → graceful error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sherlock_not_installed():
    """Missing sherlock binary returns graceful found=False result."""
    crawler = UsernameSherlockCrawler()

    with patch(
        "modules.crawlers.username_sherlock._check_sherlock_installed",
        new=AsyncMock(return_value=False),
    ):
        result = await crawler.scrape("someuser")

    assert result.found is False
    assert result.error == "sherlock_not_installed"


# ---------------------------------------------------------------------------
# Test 5: regex parsing single match
# ---------------------------------------------------------------------------


def test_regex_single_match():
    """Regex correctly parses '[+] Twitter: https://twitter.com/john'."""
    line = "[+] Twitter: https://twitter.com/john"
    matches = re.findall(r"\[\+\]\s+([^:]+):\s+(https?://\S+)", line)
    assert len(matches) == 1
    site, url = matches[0]
    assert site.strip() == "Twitter"
    assert url.strip() == "https://twitter.com/john"


# ---------------------------------------------------------------------------
# Test 6: regex parsing multiple sites
# ---------------------------------------------------------------------------


def test_regex_multiple_sites():
    """Regex extracts all [+] matches from multi-line sherlock output."""
    text = (
        "[+] Twitter: https://twitter.com/alice\n"
        "[*] Checking Instagram...\n"
        "[+] GitHub: https://github.com/alice\n"
        "[-] Reddit: Not Found!\n"
        "[+] Pinterest: https://www.pinterest.com/alice\n"
    )
    matches = re.findall(r"\[\+\]\s+([^:]+):\s+(https?://\S+)", text)
    results = [{"site": m[0].strip(), "url": m[1].strip()} for m in matches]
    assert len(results) == 3
    assert results[0] == {"site": "Twitter", "url": "https://twitter.com/alice"}
    assert results[2] == {"site": "Pinterest", "url": "https://www.pinterest.com/alice"}


# ---------------------------------------------------------------------------
# Test 7: site_count matches length of found_on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_count_matches_found_on():
    """site_count in data always equals len(found_on)."""
    crawler = UsernameSherlockCrawler()

    async def fake_run(username):
        return [
            {"site": "A", "url": "https://a.com/u"},
            {"site": "B", "url": "https://b.com/u"},
            {"site": "C", "url": "https://c.com/u"},
        ]

    with (
        patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.username_sherlock._run_sherlock", new=AsyncMock(side_effect=fake_run)
        ),
    ):
        result = await crawler.scrape("multiuser")

    assert result.data["site_count"] == len(result.data["found_on"])
    assert result.data["site_count"] == 3


# ---------------------------------------------------------------------------
# Test 8: registry check
# ---------------------------------------------------------------------------


def test_username_sherlock_registered():
    """'username_sherlock' must be in the crawler registry."""
    assert is_registered("username_sherlock")


# ---------------------------------------------------------------------------
# Test 9: identifier stored in data["username"]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_username_stored_in_data():
    """The queried username is stored in data['username']."""
    crawler = UsernameSherlockCrawler()

    async def fake_run(username):
        return []

    with (
        patch(
            "modules.crawlers.username_sherlock._check_sherlock_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.username_sherlock._run_sherlock", new=AsyncMock(side_effect=fake_run)
        ),
    ):
        result = await crawler.scrape("testhandle")

    assert result.data["username"] == "testhandle"


# ---------------------------------------------------------------------------
# Test 10: subprocess called with correct args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sherlock_subprocess_args():
    """_run_sherlock launches sherlock with the expected arguments."""
    fake_stdout = b""

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(fake_stdout, b""))

    async def _passthrough_wait_for(coro, timeout):
        return await coro

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
        patch("asyncio.wait_for", side_effect=_passthrough_wait_for),
    ):
        await _run_sherlock("targetuser")

    mock_exec.assert_called_once_with(
        "sherlock",
        "targetuser",
        "--print-found",
        "--no-color",
        "--timeout",
        "10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
