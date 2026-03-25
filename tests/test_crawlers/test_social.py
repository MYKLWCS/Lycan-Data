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


# --- _parse_profile branch: name_tag absent (72→75) ---
def test_parse_profile_no_name_tag():
    from bs4 import BeautifulSoup

    crawler = TwitterCrawler.__new__(TwitterCrawler)
    # No profile-card-fullname element — name_tag is None, branch 72→75
    html = "<html><body><div class='profile-bio'>Just a bio</div></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    data = crawler._parse_profile(soup, "noname")
    assert "display_name" not in data
    assert data["bio"] == "Just a bio"


# --- _parse_profile branch: label matches none of tweet/following/follower (88→81) ---
def test_parse_profile_unknown_stat_label():
    """Branch 88→81: label doesn't match 'tweet', 'following', or 'follower' — elif chain all False."""
    from bs4 import BeautifulSoup

    crawler = TwitterCrawler.__new__(TwitterCrawler)
    # Label "likes" matches none of the 3 elif conditions → 88→81 False branch taken
    html = """<html><body>
      <div class="profile-stat-num">42</div>
      <div class="profile-stat-header">Likes</div>
    </body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    data = crawler._parse_profile(soup, "user")
    # None of the known stat keys should be set
    assert "post_count" not in data
    assert "following_count" not in data
    assert "follower_count" not in data


# --- _parse_tweets branches (110→112, 113→115, 116→121, 119→117, 121→107) ---
def test_parse_tweets_branches():
    """Exercises all uncovered _parse_tweets branches with crafted HTML."""
    from bs4 import BeautifulSoup

    crawler = TwitterCrawler.__new__(TwitterCrawler)

    html = """<html><body>
      <!-- Item 1: no tweet-content (110→112 False), no date-tag, no stats, empty tweet (121→107 False) -->
      <div class="timeline-item"></div>
      <!-- Item 2: tweet-content present, date-tag present but no <a> inside (113→115 False), stats present but no icon-comment (119→117 False) -->
      <div class="timeline-item">
        <div class="tweet-content">Hello tweet</div>
        <div class="tweet-date"><span>no link here</span></div>
        <div class="tweet-stats">
          <div class="tweet-stat"><span class="icon-retweet"></span>5</div>
        </div>
      </div>
      <!-- Item 3: no stats element at all (116→121 False) -->
      <div class="timeline-item">
        <div class="tweet-content">Another tweet</div>
      </div>
    </body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    tweets = crawler._parse_tweets(soup)
    # Item 1: empty tweet → not appended
    # Item 2 and 3: both appended
    assert len(tweets) == 2
    assert tweets[0]["text"] == "Hello tweet"
    assert "replies" not in tweets[0]
    assert "date" not in tweets[0]


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
