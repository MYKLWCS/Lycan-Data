"""Tests for Snapchat, Pinterest, GitHub, and Discord scrapers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.discord import DiscordCrawler, snowflake_to_datetime
from modules.crawlers.github import GitHubCrawler
from modules.crawlers.pinterest import PinterestCrawler
from modules.crawlers.registry import is_registered
from modules.crawlers.snapchat import SnapchatCrawler

# ---------------------------------------------------------------------------
# Registry checks
# ---------------------------------------------------------------------------


def test_snapchat_registered():
    assert is_registered("snapchat")


def test_pinterest_registered():
    assert is_registered("pinterest")


def test_github_registered():
    assert is_registered("github")


def test_discord_registered():
    assert is_registered("discord")


# ---------------------------------------------------------------------------
# Snapchat — 3 tests
# ---------------------------------------------------------------------------

SNAPCHAT_FOUND_HTML = """
<html><head>
<meta property="og:title" content="John Doe" />
<meta property="og:image" content="https://snapchat.com/snapcode/johndoe.png" />
<meta property="og:description" content="Hey! Add me on Snapchat." />
</head></html>
"""

SNAPCHAT_NOT_FOUND_HTML = """
<html><body>This Snapcode is not available</body></html>
"""


@pytest.mark.asyncio
async def test_snapchat_found():
    crawler = SnapchatCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SNAPCHAT_FOUND_HTML

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("johndoe")

    assert result.found is True
    assert result.data["display_name"] == "John Doe"
    assert "snapcode.com" not in result.data.get("avatar_url", "")  # basic sanity
    assert result.platform == "snapchat"


@pytest.mark.asyncio
async def test_snapchat_not_found():
    crawler = SnapchatCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SNAPCHAT_NOT_FOUND_HTML

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("nonexistentuser99")

    assert result.found is False


@pytest.mark.asyncio
async def test_snapchat_http_error():
    crawler = SnapchatCrawler()

    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("anyuser")

    assert result.found is False
    assert result.data.get("error") == "http_error"


# ---------------------------------------------------------------------------
# Pinterest — 3 tests
# ---------------------------------------------------------------------------

PINTEREST_FOUND_HTML = """
<html><head>
<meta property="og:title" content="Jane Smith on Pinterest" />
<meta property="og:image" content="https://i.pinimg.com/avatar.jpg" />
<meta property="og:description" content="See what Jane Smith (janesmith) has discovered on Pinterest, the world's biggest collection of ideas. | 1,234 followers, 56 following" />
</head></html>
"""

PINTEREST_NOT_FOUND_HTML = """
<html><body>This page doesn't exist</body></html>
"""


@pytest.mark.asyncio
async def test_pinterest_found():
    crawler = PinterestCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = PINTEREST_FOUND_HTML

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("janesmith")

    assert result.found is True
    assert result.data["display_name"] == "Jane Smith on Pinterest"
    assert result.data.get("follower_count") == 1234
    assert result.data.get("avatar_url") == "https://i.pinimg.com/avatar.jpg"


@pytest.mark.asyncio
async def test_pinterest_not_found():
    crawler = PinterestCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = PINTEREST_NOT_FOUND_HTML

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("nobody99999")

    assert result.found is False


@pytest.mark.asyncio
async def test_pinterest_404():
    crawler = PinterestCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("nobody99999")

    assert result.found is False


# ---------------------------------------------------------------------------
# GitHub — 3 tests
# ---------------------------------------------------------------------------

GITHUB_PAYLOAD = {
    "login": "octocat",
    "name": "The Octocat",
    "bio": "GitHub mascot",
    "public_repos": 8,
    "followers": 9001,
    "following": 9,
    "company": "@github",
    "location": "San Francisco, CA",
    "blog": "https://github.blog",
    "avatar_url": "https://avatars.githubusercontent.com/u/583231",
    "created_at": "2011-01-25T18:44:36Z",
    "id": 583231,
}


@pytest.mark.asyncio
async def test_github_found():
    crawler = GitHubCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=GITHUB_PAYLOAD)

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("octocat")

    assert result.found is True
    assert result.data["name"] == "The Octocat"
    assert result.data["followers"] == 9001
    assert result.data["public_repos"] == 8
    assert result.profile_url == "https://github.com/octocat"
    assert result.source_reliability == 0.65


@pytest.mark.asyncio
async def test_github_not_found():
    crawler = GitHubCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("thisuserdoesnotexist99999xyz")

    assert result.found is False


@pytest.mark.asyncio
async def test_github_http_error():
    crawler = GitHubCrawler()

    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("anyuser")

    assert result.found is False
    assert result.data.get("error") == "http_error"


# ---------------------------------------------------------------------------
# Discord — 3 tests
# ---------------------------------------------------------------------------

DISCORD_PAYLOAD = {
    "id": "80351110224678912",
    "username": "Nelly",
    "discriminator": "1337",
    "avatar": "8342729096ea3675442027381ff50dfe",
    "bot": False,
}

VALID_SNOWFLAKE = "80351110224678912"


@pytest.mark.asyncio
async def test_discord_snowflake_found():
    crawler = DiscordCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=DISCORD_PAYLOAD)

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape(VALID_SNOWFLAKE)

    assert result.found is True
    assert result.data["username"] == "Nelly"
    assert result.data["discriminator"] == "1337"
    assert result.data.get("avatar_url") is not None
    assert result.data.get("created_at") is not None


@pytest.mark.asyncio
async def test_discord_non_numeric_username():
    crawler = DiscordCrawler()

    # No HTTP calls should be made for a non-numeric identifier
    with patch.object(crawler, "get", AsyncMock()) as mock_get:
        result = await crawler.scrape("someusername#1234")

    assert result.found is False
    assert "snowflake" in (result.data.get("error") or "").lower()
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_discord_http_error():
    crawler = DiscordCrawler()

    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape(VALID_SNOWFLAKE)

    assert result.found is False
    assert result.data.get("error") == "http_error"


# ---------------------------------------------------------------------------
# Utility — snowflake timestamp
# ---------------------------------------------------------------------------


def test_snowflake_to_datetime():
    # Known Discord epoch calculation: snowflake 0 → 2015-01-01
    ts = snowflake_to_datetime(0)
    assert ts.startswith("2015-01-01")

    ts2 = snowflake_to_datetime(int(VALID_SNOWFLAKE))
    assert "2015" in ts2
