"""
Unit tests for modules/crawlers/social/truth_social_profile.py

Coverage targets:
  - All pure helper functions (_is_name_search, _extract_name_query, _clean_html,
    _parse_account, _parse_statuses, _parse_profile_html)
  - TruthSocialProfileCrawler.scrape — username path, name-search path, not-found
  - _fetch_by_username — API success, API parse error, HTML fallback success,
    HTML fallback no display_name, HTML fallback non-200
  - _fetch_statuses — success, non-200, JSON list, non-list JSON, exception
  - _search_by_name — success, non-200, empty accounts, exception, with/without account_id
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.registry import is_registered
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.social.truth_social_profile import (
    TruthSocialProfileCrawler,
    _clean_html,
    _extract_name_query,
    _is_name_search,
    _parse_account,
    _parse_profile_html,
    _parse_statuses,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_crawler_registered():
    assert is_registered("truth_social_profile")


# ---------------------------------------------------------------------------
# _is_name_search
# ---------------------------------------------------------------------------


def test_is_name_search_true():
    assert _is_name_search("name:John Smith") is True


def test_is_name_search_uppercase_prefix():
    assert _is_name_search("NAME:John") is True


def test_is_name_search_false():
    assert _is_name_search("realDonaldTrump") is False


def test_is_name_search_empty():
    assert _is_name_search("") is False


# ---------------------------------------------------------------------------
# _extract_name_query
# ---------------------------------------------------------------------------


def test_extract_name_query_basic():
    assert _extract_name_query("name:John Smith") == "John Smith"


def test_extract_name_query_extra_spaces():
    assert _extract_name_query("name:  Alice  ") == "Alice"


def test_extract_name_query_no_name():
    # Degenerate: identifier shorter than 5 chars
    assert _extract_name_query("name:") == ""


# ---------------------------------------------------------------------------
# _clean_html
# ---------------------------------------------------------------------------


def test_clean_html_strips_tags():
    assert _clean_html("<p>Hello <b>world</b></p>") == "Hello  world"


def test_clean_html_no_tags():
    assert _clean_html("plain text") == "plain text"


def test_clean_html_empty():
    assert _clean_html("") == ""


def test_clean_html_nested():
    # strip() removes outer spaces produced by tag substitution
    assert _clean_html("<div><span>hi</span></div>") == "hi"


# ---------------------------------------------------------------------------
# _parse_account
# ---------------------------------------------------------------------------


def _sample_account_data(**overrides):
    base = {
        "id": "123",
        "username": "testuser",
        "display_name": "Test User",
        "note": "<p>My bio</p>",
        "avatar": "https://example.com/avatar.jpg",
        "avatar_static": "https://example.com/avatar_static.jpg",
        "created_at": "2020-01-01T00:00:00Z",
        "followers_count": 1000,
        "following_count": 50,
        "statuses_count": 300,
        "verified": True,
        "bot": False,
        "fields": [
            {"name": "Website", "value": "<a href='https://example.com'>example.com</a>"},
        ],
    }
    base.update(overrides)
    return base


def test_parse_account_full():
    data = _sample_account_data()
    result = _parse_account(data)

    assert result["account_id"] == "123"
    assert result["username"] == "testuser"
    assert result["display_name"] == "Test User"
    assert result["bio"] == "My bio"
    assert result["follower_count"] == 1000
    assert result["following_count"] == 50
    assert result["post_count"] == 300
    assert result["joined_date"] == "2020-01-01T00:00:00Z"
    assert result["profile_image_url"] == "https://example.com/avatar.jpg"
    assert result["profile_url"] == "https://truthsocial.com/@testuser"
    assert result["is_verified"] is True
    assert result["is_bot"] is False
    assert len(result["custom_fields"]) == 1
    assert result["custom_fields"][0]["label"] == "Website"


def test_parse_account_display_name_fallback_to_username():
    """When display_name is empty, fall back to username."""
    data = _sample_account_data(display_name="")
    result = _parse_account(data)
    assert result["display_name"] == "testuser"


def test_parse_account_avatar_fallback_to_static():
    """When avatar is falsy, use avatar_static."""
    data = _sample_account_data(avatar=None)
    result = _parse_account(data)
    assert result["profile_image_url"] == "https://example.com/avatar_static.jpg"


def test_parse_account_no_fields():
    data = _sample_account_data(fields=None)
    result = _parse_account(data)
    assert result["custom_fields"] == []


def test_parse_account_empty_fields_list():
    data = _sample_account_data(fields=[])
    result = _parse_account(data)
    assert result["custom_fields"] == []


def test_parse_account_no_note():
    data = _sample_account_data(note=None)
    result = _parse_account(data)
    assert result["bio"] == ""


def test_parse_account_defaults():
    """Minimal dict — all missing keys use defaults."""
    result = _parse_account({})
    assert result["account_id"] == ""
    assert result["username"] == ""
    assert result["display_name"] == ""
    assert result["follower_count"] == 0
    assert result["following_count"] == 0
    assert result["post_count"] == 0
    assert result["is_verified"] is False
    assert result["is_bot"] is False


# ---------------------------------------------------------------------------
# _parse_statuses
# ---------------------------------------------------------------------------


def _make_status(**overrides):
    base = {
        "id": "999",
        "content": "<p>Hello world</p>",
        "created_at": "2024-01-01T12:00:00Z",
        "url": "https://truthsocial.com/@user/999",
        "replies_count": 2,
        "reblogs_count": 5,
        "favourites_count": 10,
        "reblog": None,
        "language": "en",
    }
    base.update(overrides)
    return base


def test_parse_statuses_basic():
    statuses = [_make_status()]
    result = _parse_statuses(statuses)

    assert len(result) == 1
    assert result[0]["post_id"] == "999"
    assert result[0]["content"] == "Hello world"
    assert result[0]["created_at"] == "2024-01-01T12:00:00Z"
    assert result[0]["url"] == "https://truthsocial.com/@user/999"
    assert result[0]["reply_count"] == 2
    assert result[0]["retruth_count"] == 5
    assert result[0]["favourite_count"] == 10
    assert result[0]["is_retruth"] is False
    assert result[0]["language"] == "en"


def test_parse_statuses_retruth():
    """Reblogged statuses pull content/url from the reblog field."""
    reblog = {
        "content": "<p>Original post</p>",
        "url": "https://truthsocial.com/@other/111",
    }
    status = _make_status(reblog=reblog)
    result = _parse_statuses([status])

    assert result[0]["is_retruth"] is True
    assert result[0]["content"] == "Original post"
    assert result[0]["url"] == "https://truthsocial.com/@other/111"


def test_parse_statuses_skips_non_dicts():
    """Non-dict entries in the list are skipped."""
    statuses = ["not_a_dict", _make_status()]
    result = _parse_statuses(statuses)
    assert len(result) == 1


def test_parse_statuses_empty():
    assert _parse_statuses([]) == []


def test_parse_statuses_truncates_content_at_500():
    long_content = "A" * 600
    status = _make_status(content=long_content)
    result = _parse_statuses([status])
    assert len(result[0]["content"]) == 500


def test_parse_statuses_max_20():
    """Only the first 20 statuses are processed."""
    statuses = [_make_status(id=str(i)) for i in range(25)]
    result = _parse_statuses(statuses)
    assert len(result) == 20


# ---------------------------------------------------------------------------
# _parse_profile_html
# ---------------------------------------------------------------------------


def test_parse_profile_html_full():
    html = """
    <html><body>
      <div class="account__header__tabs__name">
        <h1>Full Name</h1>
        <img src="https://example.com/pic.jpg" />
      </div>
      <div class="account__header__content">Bio text here</div>
      <div class="account__header__bar">
        <div class="counter">
          <small class="counter-label">Followers</small>
          <strong class="counter-number">1000</strong>
        </div>
        <div class="counter">
          <small class="counter-label">Following</small>
          <strong class="counter-number">50</strong>
        </div>
        <div class="counter">
          <small class="counter-label">Posts</small>
          <strong class="counter-number">300</strong>
        </div>
      </div>
      <span>Joined January 2020</span>
      <div class="status">
        <p class="status__content">A post</p>
        <time datetime="2024-01-01T00:00:00Z">Jan 1</time>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)

    assert result.get("display_name") == "Full Name"
    assert "Bio text here" in result.get("bio", "")
    assert result.get("follower_count") == 1000
    assert result.get("following_count") == 50
    assert result.get("post_count") == 300
    assert "January 2020" in result.get("joined_date", "")
    assert len(result.get("recent_posts", [])) == 1
    assert result["recent_posts"][0]["created_at"] == "2024-01-01T00:00:00Z"


def test_parse_profile_html_post_without_time():
    """A post element without a time tag gets an empty created_at."""
    html = """
    <html><body>
      <h1>Someone</h1>
      <div class="status">
        <p class="status__content">A post with no time</p>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)
    assert result["recent_posts"][0]["created_at"] == ""


def test_parse_profile_html_trut_label():
    """Stat block with 'trut' label maps to post_count."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="account__header__bar">
        <div class="counter">
          <small class="counter-label">Truths</small>
          <strong class="counter-number">42</strong>
        </div>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)
    assert result.get("post_count") == 42


def test_parse_profile_html_status_label():
    """Stat block with 'status' in label maps to post_count."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="account__header__bar">
        <div class="counter">
          <small class="counter-label">Statuses</small>
          <strong class="counter-number">77</strong>
        </div>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)
    assert result.get("post_count") == 77


def test_parse_profile_html_invalid_counter_value():
    """Non-numeric counter values are skipped gracefully."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="account__header__bar">
        <div class="counter">
          <small class="counter-label">Followers</small>
          <strong class="counter-number">many</strong>
        </div>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)
    assert "follower_count" not in result


def test_parse_profile_html_h1_fallback():
    """Falls back to bare <h1> for display name when specific selectors miss."""
    html = "<html><body><h1>Just A Name</h1></body></html>"
    result = _parse_profile_html(html)
    assert result.get("display_name") == "Just A Name"


def test_parse_profile_html_display_name_h1_display_name_class():
    """Handles h1.display-name selector."""
    html = '<html><body><h1 class="display-name">Display Name</h1></body></html>'
    result = _parse_profile_html(html)
    assert result.get("display_name") == "Display Name"


def test_parse_profile_html_avatar_from_avatar_class():
    """Falls back to .account__avatar img for profile image."""
    html = """
    <html><body>
      <h1>User</h1>
      <div class="account__avatar"><img src="https://example.com/av.jpg" /></div>
    </body></html>
    """
    result = _parse_profile_html(html)
    assert result.get("profile_image_url") == "https://example.com/av.jpg"


def test_parse_profile_html_avatar_img_class():
    """Falls back to img.avatar selector."""
    html = """
    <html><body>
      <h1>User</h1>
      <img class="avatar" src="https://example.com/imgav.jpg" />
    </body></html>
    """
    result = _parse_profile_html(html)
    assert result.get("profile_image_url") == "https://example.com/imgav.jpg"


def test_parse_profile_html_no_posts():
    """Returns no recent_posts key when no post elements found."""
    html = "<html><body><h1>Name</h1></body></html>"
    result = _parse_profile_html(html)
    assert "recent_posts" not in result


def test_parse_profile_html_empty_string():
    """Empty HTML returns empty dict without raising."""
    result = _parse_profile_html("")
    assert isinstance(result, dict)


def test_parse_profile_html_no_joined_date():
    """No 'Joined' string means no joined_date key."""
    html = "<html><body><h1>Name</h1></body></html>"
    result = _parse_profile_html(html)
    assert "joined_date" not in result


def test_parse_profile_html_beautifulsoup_exception():
    """When BeautifulSoup raises, the except branch is hit and {} returned."""
    with patch("bs4.BeautifulSoup", side_effect=RuntimeError("bs4 broken")):
        result = _parse_profile_html("<html></html>")
    assert result == {}


# ---------------------------------------------------------------------------
# TruthSocialProfileCrawler — class attributes
# ---------------------------------------------------------------------------


def test_crawler_attributes():
    crawler = TruthSocialProfileCrawler()
    assert crawler.platform == "truth_social_profile"
    assert crawler.source_reliability == 0.70
    assert crawler.requires_tor is False
    assert crawler.proxy_tier == "datacenter"


# ---------------------------------------------------------------------------
# TruthSocialProfileCrawler.scrape — username path
# ---------------------------------------------------------------------------


async def test_scrape_username_found():
    crawler = TruthSocialProfileCrawler()
    profile = {
        "account_id": "1",
        "username": "testuser",
        "display_name": "Test User",
        "profile_url": "https://truthsocial.com/@testuser",
    }
    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(return_value=profile)):
        result = await crawler.scrape("testuser")

    assert isinstance(result, CrawlerResult)
    assert result.found is True
    assert result.data["username"] == "testuser"
    assert result.profile_url == "https://truthsocial.com/@testuser"
    assert result.platform == "truth_social_profile"


async def test_scrape_username_not_found():
    crawler = TruthSocialProfileCrawler()
    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("ghostuser")

    assert result.found is False
    assert result.data.get("error") == "not_found"


async def test_scrape_username_strips_at_prefix():
    """Leading @ is removed before lookup."""
    crawler = TruthSocialProfileCrawler()
    captured = {}

    async def fake_fetch(username):
        captured["username"] = username
        return None

    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(side_effect=fake_fetch)):
        await crawler.scrape("@handle")

    assert captured["username"] == "handle"


async def test_scrape_username_no_profile_url():
    """profile_url=None when profile data has no profile_url."""
    crawler = TruthSocialProfileCrawler()
    profile = {"account_id": "5", "username": "x", "display_name": "X"}
    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(return_value=profile)):
        result = await crawler.scrape("x")

    assert result.found is True
    assert result.profile_url is None


# ---------------------------------------------------------------------------
# TruthSocialProfileCrawler.scrape — name search path
# ---------------------------------------------------------------------------


async def test_scrape_name_search_found():
    crawler = TruthSocialProfileCrawler()
    profile = {
        "account_id": "2",
        "username": "johnsmith",
        "display_name": "John Smith",
        "profile_url": "https://truthsocial.com/@johnsmith",
    }
    with patch.object(crawler, "_search_by_name", new=AsyncMock(return_value=profile)):
        result = await crawler.scrape("name:John Smith")

    assert result.found is True
    assert result.data["display_name"] == "John Smith"


async def test_scrape_name_search_not_found():
    crawler = TruthSocialProfileCrawler()
    with patch.object(crawler, "_search_by_name", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("name:Nobody Known")

    assert result.found is False
    assert result.data.get("error") == "not_found"


# ---------------------------------------------------------------------------
# _fetch_by_username
# ---------------------------------------------------------------------------


async def test_fetch_by_username_api_success():
    """API lookup returns 200 with valid account; statuses fetched via account_id."""
    crawler = TruthSocialProfileCrawler()
    account_payload = {
        "id": "42",
        "username": "alice",
        "display_name": "Alice",
        "note": "Bio",
        "followers_count": 10,
        "following_count": 5,
        "statuses_count": 20,
        "bot": False,
        "verified": False,
        "fields": [],
    }
    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json = MagicMock(return_value=account_payload)

    posts = [{"post_id": "1", "content": "hello"}]
    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_api_resp)):
        with patch.object(crawler, "_fetch_statuses", new=AsyncMock(return_value=posts)):
            result = await crawler._fetch_by_username("alice")

    assert result is not None
    assert result["account_id"] == "42"
    assert result["recent_posts"] == posts


async def test_fetch_by_username_api_non_200_falls_to_html():
    """Non-200 API response triggers HTML fallback path."""
    crawler = TruthSocialProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 401

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = """
    <html><body>
      <h1>Bob</h1>
    </body></html>
    """

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("bob")

    assert result is not None
    assert result["display_name"] == "Bob"
    assert result["username"] == "bob"


async def test_fetch_by_username_api_parse_exception_falls_to_html():
    """JSON parse exception on API response triggers HTML fallback."""
    crawler = TruthSocialProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json = MagicMock(side_effect=ValueError("bad json"))

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Carol</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("carol")

    assert result is not None
    assert result["display_name"] == "Carol"


async def test_fetch_by_username_html_no_display_name_returns_none():
    """HTML fallback that yields no display_name returns None."""
    crawler = TruthSocialProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><p>Nothing useful</p></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("ghost")

    assert result is None


async def test_fetch_by_username_html_non_200_returns_none():
    """HTML fallback with non-200/206 status returns None."""
    crawler = TruthSocialProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 404

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("ghost")

    assert result is None


async def test_fetch_by_username_html_none_response_returns_none():
    """HTML fallback returning None response returns None."""
    crawler = TruthSocialProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    get_mock = AsyncMock(side_effect=[api_resp, None])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("ghost")

    assert result is None


async def test_fetch_by_username_api_none_falls_to_html():
    """get() returning None for API triggers HTML fallback."""
    crawler = TruthSocialProfileCrawler()

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Dave</h1></body></html>"

    get_mock = AsyncMock(side_effect=[None, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("dave")

    assert result is not None
    assert result["display_name"] == "Dave"


async def test_fetch_by_username_html_206_status_ok():
    """206 Partial Content is treated as success for HTML fallback."""
    crawler = TruthSocialProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 206
    html_resp.text = "<html><body><h1>Eve</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("eve")

    assert result is not None
    assert result["display_name"] == "Eve"


# ---------------------------------------------------------------------------
# _fetch_statuses
# ---------------------------------------------------------------------------


async def test_fetch_statuses_success():
    crawler = TruthSocialProfileCrawler()
    raw = [
        {
            "id": "1",
            "content": "<p>Post one</p>",
            "created_at": "2024-01-01T00:00:00Z",
            "url": "https://truthsocial.com/@u/1",
            "replies_count": 0,
            "reblogs_count": 1,
            "favourites_count": 3,
            "reblog": None,
            "language": "en",
        }
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=raw)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        posts = await crawler._fetch_statuses("42")

    assert len(posts) == 1
    assert posts[0]["content"] == "Post one"


async def test_fetch_statuses_none_response():
    crawler = TruthSocialProfileCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        posts = await crawler._fetch_statuses("42")
    assert posts == []


async def test_fetch_statuses_non_200():
    crawler = TruthSocialProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        posts = await crawler._fetch_statuses("42")

    assert posts == []


async def test_fetch_statuses_non_list_json():
    """If the JSON response is not a list, return empty."""
    crawler = TruthSocialProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"error": "unauthorized"})

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        posts = await crawler._fetch_statuses("42")

    assert posts == []


async def test_fetch_statuses_json_exception():
    """JSON decode exception returns empty list."""
    crawler = TruthSocialProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(side_effect=ValueError("bad"))

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        posts = await crawler._fetch_statuses("42")

    assert posts == []


# ---------------------------------------------------------------------------
# _search_by_name
# ---------------------------------------------------------------------------


async def test_search_by_name_success_with_posts():
    crawler = TruthSocialProfileCrawler()
    account = {
        "id": "10",
        "username": "john",
        "display_name": "John Smith",
        "note": "",
        "followers_count": 0,
        "following_count": 0,
        "statuses_count": 0,
        "bot": False,
        "verified": False,
        "fields": [],
    }
    search_payload = {"accounts": [account]}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=search_payload)

    posts = [{"post_id": "99", "content": "hi"}]
    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        with patch.object(crawler, "_fetch_statuses", new=AsyncMock(return_value=posts)):
            result = await crawler._search_by_name("John Smith")

    assert result is not None
    assert result["username"] == "john"
    assert result["recent_posts"] == posts


async def test_search_by_name_empty_accounts():
    crawler = TruthSocialProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"accounts": []})

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler._search_by_name("Nobody")

    assert result is None


async def test_search_by_name_none_response():
    crawler = TruthSocialProfileCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler._search_by_name("Test")
    assert result is None


async def test_search_by_name_non_200():
    crawler = TruthSocialProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler._search_by_name("Test")

    assert result is None


async def test_search_by_name_json_exception():
    """JSON parse exception returns None."""
    crawler = TruthSocialProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(side_effect=ValueError("bad json"))

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler._search_by_name("Test")

    assert result is None


async def test_search_by_name_no_account_id_skips_statuses():
    """Account with no account_id skips _fetch_statuses."""
    crawler = TruthSocialProfileCrawler()
    account = {
        # id intentionally absent
        "username": "anon",
        "display_name": "Anon",
        "note": "",
        "followers_count": 0,
        "following_count": 0,
        "statuses_count": 0,
        "bot": False,
        "verified": False,
        "fields": [],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"accounts": [account]})

    fetch_statuses_mock = AsyncMock()
    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        with patch.object(crawler, "_fetch_statuses", new=fetch_statuses_mock):
            result = await crawler._search_by_name("Anon")

    # account_id is "" (falsy) — _fetch_statuses must not be called
    fetch_statuses_mock.assert_not_called()
    assert result is not None
    assert result["username"] == "anon"


# ---------------------------------------------------------------------------
# _parse_profile_html — missing branches:
#   157→143: stat label matches neither follower/following/post/trut/status
#   172→170: Joined string in a tag whose .parent is None
#   181→178: post element has no text_el (if text_el: False)
# ---------------------------------------------------------------------------


def test_parse_profile_html_unknown_stat_label_skipped():
    """Branch 157→143: counter with unrecognised label — no key set, loop continues."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="account__header__bar">
        <div class="counter">
          <small class="counter-label">Views</small>
          <strong class="counter-number">9999</strong>
        </div>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)
    assert "follower_count" not in result
    assert "following_count" not in result
    assert "post_count" not in result


def test_parse_profile_html_joined_parent_none():
    """Branch 172→170: 'Joined' string found at top-level with parent=None won't crash."""
    # In BeautifulSoup the NavigableString for a top-level text node has parent=document
    # We simulate the branch by patching soup.find_all to return a string whose parent is None
    from unittest.mock import patch

    class FakeNavigableString(str):
        parent = None

    with patch("bs4.BeautifulSoup") as mock_bs:
        fake_soup = MagicMock()
        # find_all returns our fake string whose parent is None
        fake_soup.find_all.return_value = [FakeNavigableString("Joined 2020")]
        fake_soup.select_one.return_value = None
        fake_soup.select.return_value = []
        mock_bs.return_value = fake_soup

        result = _parse_profile_html("<html><body>Joined 2020</body></html>")

    # joined_date must NOT be set (parent was None)
    assert "joined_date" not in result


def test_parse_profile_html_post_without_text_el_not_appended():
    """Branch 181→178: post element with no matching text selector → not appended."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="status">
        <!-- no .status__content, .content, or p inside -->
        <time datetime="2024-06-01T00:00:00Z">June 1</time>
      </div>
    </body></html>
    """
    result = _parse_profile_html(html)
    # The status element has a time but no text_el → if text_el: False → not appended
    assert "recent_posts" not in result
