from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.facebook import FacebookCrawler
from modules.crawlers.instagram import InstagramCrawler, _parse_count
from modules.crawlers.registry import is_registered
from modules.crawlers.twitter import TwitterCrawler, _parse_stat


# --- Registry checks ---
def test_instagram_registered():
    assert is_registered("instagram")


def test_facebook_registered():
    assert is_registered("facebook")


def test_twitter_registered():
    assert is_registered("twitter")


# --- _parse_count utility ---
def test_parse_count_k():
    assert _parse_count("1.5K") == 1500


def test_parse_count_m():
    assert _parse_count("2.3M") == 2300000


def test_parse_count_plain():
    assert _parse_count("12,345") == 12345


def test_parse_count_invalid():
    assert _parse_count("abc") is None


# --- _parse_stat utility ---
def test_parse_stat_k():
    assert _parse_stat("4.5K") == 4500


def test_parse_stat_empty():
    assert _parse_stat("") == 0


# --- Instagram scraper mock ---
@pytest.mark.asyncio
async def test_instagram_private_account():
    crawler = InstagramCrawler()
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="This Account is Private")
    mock_page.__aenter__ = AsyncMock(return_value=mock_page)
    mock_page.__aexit__ = AsyncMock(return_value=False)

    with patch.object(crawler, "page", return_value=mock_page):
        result = await crawler.scrape("privateuserxyz")

    assert result.found is True
    assert result.data.get("is_private") is True


@pytest.mark.asyncio
async def test_instagram_not_found():
    crawler = InstagramCrawler()
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="Sorry, this page isn't available")
    mock_page.__aenter__ = AsyncMock(return_value=mock_page)
    mock_page.__aexit__ = AsyncMock(return_value=False)

    with patch.object(crawler, "page", return_value=mock_page):
        result = await crawler.scrape("definitelynotarealuser99999")

    assert result.found is False


# --- Twitter nitter mock ---
@pytest.mark.asyncio
async def test_twitter_not_found():
    crawler = TwitterCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><div class='error-panel'>User not found</div></html>"

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("definitelynotarealuser99999x")

    assert result.found is False


@pytest.mark.asyncio
async def test_twitter_parses_profile():
    from bs4 import BeautifulSoup

    crawler = TwitterCrawler()
    html = """
    <html><body>
    <div class="profile-card-fullname">Test User</div>
    <div class="profile-bio">This is a bio</div>
    <div class="profile-stat-num">1.5K</div><div class="profile-stat-header">Tweets</div>
    <div class="profile-stat-num">500</div><div class="profile-stat-header">Following</div>
    <div class="profile-stat-num">10K</div><div class="profile-stat-header">Followers</div>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("testuser")

    assert result.found is True
    assert result.data["display_name"] == "Test User"
    assert result.data["bio"] == "This is a bio"
    assert result.data["follower_count"] == 10000
