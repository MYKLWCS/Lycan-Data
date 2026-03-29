"""
Unit tests for modules/crawlers/social/vk_profile.py

Coverage targets:
  - All pure helpers: _is_username, _extract_username, _parse_name_country,
    _parse_vk_api_user, _parse_vk_html
  - VkProfileCrawler.scrape — username path, name-search path, not-found
  - _fetch_by_username — API success, API None/non-200, parse exception,
    HTML fallback success, HTML fallback no display_name, HTML 404
  - _search_by_name — API success, API None/non-200, parse exception,
    HTML fallback success/failure
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.registry import is_registered
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.social.vk_profile import (
    VkProfileCrawler,
    _extract_username,
    _is_username,
    _parse_name_country,
    _parse_vk_api_user,
    _parse_vk_html,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_crawler_registered():
    assert is_registered("vk_profile")


# ---------------------------------------------------------------------------
# _is_username
# ---------------------------------------------------------------------------


def test_is_username_plain_handle():
    assert _is_username("durov") is True


def test_is_username_with_pipe_returns_false():
    assert _is_username("John Smith | Russia") is False


def test_is_username_with_space_returns_false():
    assert _is_username("John Smith") is False


def test_is_username_with_leading_trailing_spaces():
    # Strip first — single token after strip means username
    assert _is_username("  durov  ") is True


def test_is_username_url_style():
    assert _is_username("vk.com/durov") is True


# ---------------------------------------------------------------------------
# _extract_username
# ---------------------------------------------------------------------------


def test_extract_username_plain():
    assert _extract_username("durov") == "durov"


def test_extract_username_https():
    assert _extract_username("https://vk.com/durov") == "durov"


def test_extract_username_http():
    assert _extract_username("http://vk.com/durov") == "durov"


def test_extract_username_no_scheme():
    assert _extract_username("vk.com/durov") == "durov"


def test_extract_username_strips_whitespace():
    assert _extract_username("  durov  ") == "durov"


def test_extract_username_uppercase_url():
    """Case-insensitive prefix matching."""
    assert _extract_username("HTTPS://VK.COM/durov") == "durov"


# ---------------------------------------------------------------------------
# _parse_name_country
# ---------------------------------------------------------------------------


def test_parse_name_country_with_country():
    name, country = _parse_name_country("John Smith | Russia")
    assert name == "John Smith"
    assert country == "Russia"


def test_parse_name_country_no_country():
    name, country = _parse_name_country("John Smith")
    assert name == "John Smith"
    assert country == ""


def test_parse_name_country_multiple_pipes_splits_on_first():
    name, country = _parse_name_country("John | Smith | Russia")
    assert name == "John"
    assert country == "Smith | Russia"


def test_parse_name_country_empty():
    name, country = _parse_name_country("")
    assert name == ""
    assert country == ""


# ---------------------------------------------------------------------------
# _parse_vk_api_user — dict with response list
# ---------------------------------------------------------------------------


def _sample_vk_user(**overrides):
    base = {
        "id": 1234,
        "first_name": "Ivan",
        "last_name": "Petrov",
        "deactivated": "",
        "status": "Living the dream",
        "bdate": "1.1.1990",
        "city": {"title": "Moscow"},
        "country": {"title": "Russia"},
        "counters": {
            "followers": 500,
            "friends": 100,
            "photos": 50,
            "wall": 200,
            "groups": 10,
        },
        "photo_max_orig": "https://example.com/photo.jpg",
        "photo_max": "https://example.com/photo_small.jpg",
        "education": {"university_name": "MSU"},
        "career": [{"company": "Acme", "position": "Dev", "from": 2015, "until": 2020}],
    }
    base.update(overrides)
    return base


def test_parse_vk_api_user_dict_response_list():
    data = {"response": [_sample_vk_user()]}
    result = _parse_vk_api_user(data)

    assert result is not None
    assert result["vk_id"] == "1234"
    assert result["display_name"] == "Ivan Petrov"
    assert result["first_name"] == "Ivan"
    assert result["last_name"] == "Petrov"
    assert result["is_active"] is True
    assert result["status"] == "Living the dream"
    assert result["birth_date"] == "1.1.1990"
    assert result["city"] == "Moscow"
    assert result["country"] == "Russia"
    assert result["follower_count"] == 500
    assert result["friends_count"] == 100
    assert result["photos_count"] == 50
    assert result["posts_count"] == 200
    assert result["groups_count"] == 10
    assert result["profile_image_url"] == "https://example.com/photo.jpg"
    assert result["education_university"] == "MSU"
    assert len(result["career"]) == 1
    assert result["career"][0]["company"] == "Acme"
    assert result["profile_url"] == "https://vk.com/id1234"


def test_parse_vk_api_user_response_dict_items():
    """response is a dict with 'items' key (search response format)."""
    data = {"response": {"items": [_sample_vk_user()]}}
    result = _parse_vk_api_user(data)
    assert result is not None
    assert result["vk_id"] == "1234"


def test_parse_vk_api_user_response_dict_empty_items():
    """response dict with empty items — user falls back to {}, returns sparse dict."""
    data = {"response": {"items": []}}
    result = _parse_vk_api_user(data)
    # user = {} produces a valid result with empty/default fields
    assert result is not None
    assert result["display_name"] == ""
    assert result["vk_id"] == ""


def test_parse_vk_api_user_bare_list():
    """Input is a raw list (not wrapped in dict)."""
    result = _parse_vk_api_user([_sample_vk_user()])
    assert result is not None
    assert result["vk_id"] == "1234"


def test_parse_vk_api_user_empty_response_list():
    data = {"response": []}
    result = _parse_vk_api_user(data)
    assert result is None


def test_parse_vk_api_user_none_input():
    result = _parse_vk_api_user(None)
    assert result is None


def test_parse_vk_api_user_empty_list():
    result = _parse_vk_api_user([])
    assert result is None


def test_parse_vk_api_user_string_input():
    result = _parse_vk_api_user("not_valid")
    assert result is None


def test_parse_vk_api_user_deactivated():
    data = {"response": [_sample_vk_user(deactivated="deleted")]}
    result = _parse_vk_api_user(data)
    assert result["is_active"] is False
    assert result["deactivated"] == "deleted"


def test_parse_vk_api_user_city_as_string():
    """city field as plain string (non-dict) is used as-is."""
    data = {"response": [_sample_vk_user(city="Kazan")]}
    result = _parse_vk_api_user(data)
    assert result["city"] == "Kazan"


def test_parse_vk_api_user_country_as_string():
    data = {"response": [_sample_vk_user(country="Belarus")]}
    result = _parse_vk_api_user(data)
    assert result["country"] == "Belarus"


def test_parse_vk_api_user_no_photo_max_orig_fallback():
    """Falls back to photo_max when photo_max_orig is absent/empty."""
    user = _sample_vk_user()
    del user["photo_max_orig"]
    data = {"response": [user]}
    result = _parse_vk_api_user(data)
    assert result["profile_image_url"] == "https://example.com/photo_small.jpg"


def test_parse_vk_api_user_no_counters():
    data = {"response": [_sample_vk_user(counters=None)]}
    result = _parse_vk_api_user(data)
    assert result["follower_count"] == 0


def test_parse_vk_api_user_no_career():
    data = {"response": [_sample_vk_user(career=None)]}
    result = _parse_vk_api_user(data)
    assert result["career"] == []


def test_parse_vk_api_user_career_non_dict_items():
    """Non-dict items in career list are skipped."""
    data = {"response": [_sample_vk_user(career=["not_a_dict"])]}
    result = _parse_vk_api_user(data)
    assert result["career"] == []


def test_parse_vk_api_user_education_non_dict():
    """education as non-dict yields empty university."""
    data = {"response": [_sample_vk_user(education="MSU")]}
    result = _parse_vk_api_user(data)
    assert result["education_university"] == ""


def test_parse_vk_api_user_no_education():
    data = {"response": [_sample_vk_user(education=None)]}
    result = _parse_vk_api_user(data)
    assert result["education_university"] == ""


def test_parse_vk_api_user_response_not_list_or_dict():
    """response is neither list nor dict returns None."""
    data = {"response": 42}
    result = _parse_vk_api_user(data)
    assert result is None


def test_parse_vk_api_user_exception_returns_none():
    """An unexpected exception inside the try block is caught and returns None."""

    # Passing a dict that causes an AttributeError internally by using a mock
    # that raises when .get() is called inside _parse_vk_api_user.
    class Exploder:
        def get(self, *a, **kw):
            raise RuntimeError("forced failure")

    result = _parse_vk_api_user({"response": [Exploder()]})
    assert result is None


# ---------------------------------------------------------------------------
# _parse_vk_html
# ---------------------------------------------------------------------------


def test_parse_vk_html_full():
    html = """
    <html><body>
      <h1 class="profile_name">Alexei Navalny</h1>
      <span class="status">Fight for the future</span>
      <span class="pp_city">Moscow</span>
      <span>1,234 followers</span>
      <div class="profile_avatar"><img src="https://example.com/av.jpg" /></div>
      <div class="wall_item">
        <p class="pi_text">Post content here</p>
        <time class="pi_date">Jan 1, 2024</time>
      </div>
    </body></html>
    """
    result = _parse_vk_html(html)

    assert result.get("display_name") == "Alexei Navalny"
    assert result.get("status") == "Fight for the future"
    assert result.get("city") == "Moscow"
    assert result.get("follower_count") == 1234
    assert result.get("profile_image_url") == "https://example.com/av.jpg"
    assert len(result.get("recent_posts", [])) == 1
    assert result["recent_posts"][0]["text"] == "Post content here"


def test_parse_vk_html_h1_fallback():
    """Falls back to bare h1 when .profile_name absent."""
    html = "<html><body><h1>Name Here</h1></body></html>"
    result = _parse_vk_html(html)
    assert result.get("display_name") == "Name Here"


def test_parse_vk_html_name_class_fallback():
    """Falls back to .name when h1 variants absent."""
    html = '<html><body><span class="name">Span Name</span></body></html>'
    result = _parse_vk_html(html)
    assert result.get("display_name") == "Span Name"


def test_parse_vk_html_userpic_avatar():
    """Uses .userpic img as avatar fallback."""
    html = """
    <html><body>
      <h1>User</h1>
      <div class="userpic"><img src="https://example.com/userpic.jpg" /></div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result.get("profile_image_url") == "https://example.com/userpic.jpg"


def test_parse_vk_html_photo_class_avatar():
    """Uses .photo img as final avatar fallback."""
    html = """
    <html><body>
      <h1>User</h1>
      <div class="photo"><img src="https://example.com/photo.jpg" /></div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result.get("profile_image_url") == "https://example.com/photo.jpg"


def test_parse_vk_html_follower_count_with_spaces():
    """Handles follower counts with space-separated digits."""
    html = """
    <html><body>
      <h1>User</h1>
      <span>1 500 followers</span>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result.get("follower_count") == 1500


def test_parse_vk_html_no_posts():
    html = "<html><body><h1>Name</h1></body></html>"
    result = _parse_vk_html(html)
    assert "recent_posts" not in result


def test_parse_vk_html_post_without_text_el():
    """Post element with no text element still appended (empty text)."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="wall_item">
        <time class="pi_date">Jan 1</time>
      </div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert len(result.get("recent_posts", [])) == 1
    assert result["recent_posts"][0]["text"] == ""


def test_parse_vk_html_post_without_date_el():
    """Post element with no date element gives empty date."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="wall_item">
        <p class="pi_text">Some text</p>
      </div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result["recent_posts"][0]["date"] == ""


def test_parse_vk_html_post_css_post_class():
    """Handles .post class elements."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="post">
        <p class="wall_post_text">Posted via post class</p>
      </div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result["recent_posts"][0]["text"] == "Posted via post class"


def test_parse_vk_html_post_underscore_post_class():
    """Handles ._post class elements."""
    html = """
    <html><body>
      <h1>Name</h1>
      <div class="_post">
        <p class="post_text">Underscore post</p>
      </div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result["recent_posts"][0]["text"] == "Underscore post"


def test_parse_vk_html_empty_string():
    result = _parse_vk_html("")
    assert isinstance(result, dict)


def test_parse_vk_html_follower_count_non_numeric_after_match():
    """regex matches but value can't be int() — ValueError is caught silently."""
    # Craft HTML so re.search finds a match whose stripped text is non-numeric
    # Use a Unicode digit-like char that passes the digit pattern but fails int()
    # The regex pattern ([\d\s,]+) won't match №, so this path is hit only
    # when the matched group produces something int() rejects.
    # Force it by patching re.search to return a group() that's non-numeric.
    import re as _re

    original_search = _re.search
    call_count = 0

    def patched_search(pattern, string, *args, **kwargs):
        nonlocal call_count
        result = original_search(pattern, string, *args, **kwargs)
        # On the follower-count int() cast attempt, return a fake match
        if pattern == r"([\d\s,]+)" and call_count == 0:
            call_count += 1

            class FakeMatch:
                def group(self, n):
                    return "abc"  # will raise ValueError on int()

            return FakeMatch()
        return result

    with patch("modules.crawlers.social.vk_profile.re.search", side_effect=patched_search):
        result = _parse_vk_html(
            "<html><body><h1>User</h1><span>1,000 followers</span></body></html>"
        )
    # follower_count should NOT be set because int() raised
    assert "follower_count" not in result


def test_parse_vk_html_beautifulsoup_exception():
    """When BeautifulSoup raises, the except branch is hit and {} returned."""
    with patch("bs4.BeautifulSoup", side_effect=RuntimeError("bs4 broken")):
        result = _parse_vk_html("<html></html>")
    assert result == {}


def test_parse_vk_html_city_data_field():
    """Picks up city from [data-field='city'] attribute."""
    html = """
    <html><body>
      <h1>User</h1>
      <span data-field="city">Sochi</span>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result.get("city") == "Sochi"


def test_parse_vk_html_profile_status_class():
    """Picks up status from .profile_status class."""
    html = """
    <html><body>
      <h1>User</h1>
      <div class="profile_status">Status text here</div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result.get("status") == "Status text here"


def test_parse_vk_html_page_block_status_class():
    """Picks up status from .page_block_status class."""
    html = """
    <html><body>
      <h1>User</h1>
      <div class="page_block_status">Block status</div>
    </body></html>
    """
    result = _parse_vk_html(html)
    assert result.get("status") == "Block status"


# ---------------------------------------------------------------------------
# VkProfileCrawler — class attributes
# ---------------------------------------------------------------------------


def test_crawler_attributes():
    crawler = VkProfileCrawler()
    assert crawler.platform == "vk_profile"
    assert crawler.source_reliability == 0.72
    assert crawler.requires_tor is True
    assert crawler.proxy_tier == "residential"


# ---------------------------------------------------------------------------
# VkProfileCrawler.scrape — username path
# ---------------------------------------------------------------------------


async def test_scrape_username_found():
    crawler = VkProfileCrawler()
    profile = {
        "vk_id": "1",
        "display_name": "Test User",
        "profile_url": "https://vk.com/id1",
    }
    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(return_value=profile)):
        result = await crawler.scrape("testuser")

    assert isinstance(result, CrawlerResult)
    assert result.found is True
    assert result.data["display_name"] == "Test User"
    assert result.profile_url == "https://vk.com/id1"
    assert result.platform == "vk_profile"


async def test_scrape_username_not_found():
    crawler = VkProfileCrawler()
    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("ghostuser")

    assert result.found is False
    assert result.data.get("error") == "not_found"


async def test_scrape_username_no_profile_url():
    """Returns profile_url=None when data has no profile_url."""
    crawler = VkProfileCrawler()
    profile = {"vk_id": "99", "display_name": "X"}
    with patch.object(crawler, "_fetch_by_username", new=AsyncMock(return_value=profile)):
        result = await crawler.scrape("xuser")

    assert result.profile_url is None


async def test_scrape_name_search_routes_correctly():
    """'|' in identifier routes to _search_by_name."""
    crawler = VkProfileCrawler()
    profile = {
        "vk_id": "2",
        "display_name": "Ivan Petrov",
        "profile_url": "https://vk.com/id2",
    }
    captured = {}

    async def fake_search(name, country):
        captured["name"] = name
        captured["country"] = country
        return profile

    with patch.object(crawler, "_search_by_name", new=AsyncMock(side_effect=fake_search)):
        result = await crawler.scrape("Ivan Petrov | Russia")

    assert captured["name"] == "Ivan Petrov"
    assert captured["country"] == "Russia"
    assert result.found is True


async def test_scrape_name_search_not_found():
    crawler = VkProfileCrawler()
    with patch.object(crawler, "_search_by_name", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Nobody Known | Nowhere")

    assert result.found is False
    assert result.data.get("error") == "not_found"


# ---------------------------------------------------------------------------
# _fetch_by_username
# ---------------------------------------------------------------------------


async def test_fetch_by_username_api_success():
    crawler = VkProfileCrawler()
    api_payload = {"response": [_sample_vk_user()]}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=api_payload)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler._fetch_by_username("durov")

    assert result is not None
    assert result["vk_id"] == "1234"


async def test_fetch_by_username_api_none_falls_to_html():
    """get() returns None → skip API, fall to HTML."""
    crawler = VkProfileCrawler()

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Bob</h1></body></html>"

    get_mock = AsyncMock(side_effect=[None, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("bob")

    assert result is not None
    assert result["display_name"] == "Bob"
    assert result["profile_url"] == "https://vk.com/bob"


async def test_fetch_by_username_api_non_200_falls_to_html():
    """API returns 403 → HTML fallback."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Carol</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("carol")

    assert result is not None
    assert result["display_name"] == "Carol"


async def test_fetch_by_username_api_parse_returns_none_falls_to_html():
    """_parse_vk_api_user returns None → HTML fallback."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json = MagicMock(return_value={"response": []})  # empty → None

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Dave</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("dave")

    assert result is not None
    assert result["display_name"] == "Dave"


async def test_fetch_by_username_api_json_exception_falls_to_html():
    """JSON decode error on API response → HTML fallback."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json = MagicMock(side_effect=ValueError("bad"))

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Eve</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("eve")

    assert result is not None
    assert result["display_name"] == "Eve"


async def test_fetch_by_username_html_no_display_name_returns_none():
    """HTML fallback with no display_name returns None."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><p>No name here</p></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("ghost")

    assert result is None


async def test_fetch_by_username_html_non_200_returns_none():
    """HTML 404 → return None."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 404

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("nobody")

    assert result is None


async def test_fetch_by_username_html_206_ok():
    """206 Partial Content is accepted as valid HTML response."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 206
    html_resp.text = "<html><body><h1>Frank</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("frank")

    assert result is not None
    assert result["display_name"] == "Frank"


async def test_fetch_by_username_html_none_response_returns_none():
    """HTML get() returning None → return None."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    get_mock = AsyncMock(side_effect=[api_resp, None])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._fetch_by_username("nobody")

    assert result is None


# ---------------------------------------------------------------------------
# _search_by_name
# ---------------------------------------------------------------------------


async def test_search_by_name_api_success():
    crawler = VkProfileCrawler()
    api_payload = {"response": [_sample_vk_user()]}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=api_payload)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler._search_by_name("Ivan Petrov", "Russia")

    assert result is not None
    assert result["vk_id"] == "1234"


async def test_search_by_name_api_none_falls_to_html():
    """API get() None → HTML people-search fallback."""
    crawler = VkProfileCrawler()

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Greg</h1></body></html>"

    get_mock = AsyncMock(side_effect=[None, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Greg", "")

    assert result is not None
    assert result["display_name"] == "Greg"


async def test_search_by_name_api_non_200_falls_to_html():
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Hannah</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Hannah", "")

    assert result is not None
    assert result["display_name"] == "Hannah"


async def test_search_by_name_api_parse_none_falls_to_html():
    """_parse_vk_api_user returns None → HTML fallback."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json = MagicMock(return_value={"response": []})

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Iris</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Iris", "")

    assert result is not None
    assert result["display_name"] == "Iris"


async def test_search_by_name_api_exception_falls_to_html():
    """JSON decode exception on API → HTML fallback."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json = MagicMock(side_effect=ValueError("oops"))

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><h1>Jake</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Jake", "")

    assert result is not None
    assert result["display_name"] == "Jake"


async def test_search_by_name_html_non_200_returns_none():
    """HTML fallback 404 returns None."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 404

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Nobody", "")

    assert result is None


async def test_search_by_name_html_none_response_returns_none():
    """HTML fallback None response returns None."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    get_mock = AsyncMock(side_effect=[api_resp, None])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Nobody", "")

    assert result is None


async def test_search_by_name_html_no_display_name_returns_none():
    """HTML fallback that yields no display_name returns None."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html><body><p>No name here</p></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Nobody", "")

    assert result is None


async def test_search_by_name_html_206_ok():
    """206 response accepted for HTML search fallback."""
    crawler = VkProfileCrawler()

    api_resp = MagicMock()
    api_resp.status_code = 403

    html_resp = MagicMock()
    html_resp.status_code = 206
    html_resp.text = "<html><body><h1>Kim</h1></body></html>"

    get_mock = AsyncMock(side_effect=[api_resp, html_resp])
    with patch.object(crawler, "get", new=get_mock):
        result = await crawler._search_by_name("Kim", "")

    assert result is not None
    assert result["display_name"] == "Kim"


# ---------------------------------------------------------------------------
# _parse_vk_html — missing branches:
#   168→166: "follower" string in an element whose .parent is None
#   171→166: "follower" string found but regex doesn't match count
# ---------------------------------------------------------------------------


def test_parse_vk_html_follower_string_parent_none():
    """Branch 168→166: NavigableString matching 'follower' but parent is None — skipped."""
    from unittest.mock import patch

    class FakeNavigableString(str):
        parent = None

    with patch("bs4.BeautifulSoup") as mock_bs:
        fake_soup = MagicMock()
        fake_soup.select_one.return_value = None
        fake_soup.find.return_value = None
        # find_all for follower returns a string with no parent
        fake_soup.find_all.return_value = [FakeNavigableString("1000 followers")]
        fake_soup.select.return_value = []
        mock_bs.return_value = fake_soup

        result = _parse_vk_html(
            "<html><body><h1>User</h1><span>1000 followers</span></body></html>"
        )

    # follower_count not set because parent was None
    assert "follower_count" not in result


def test_parse_vk_html_follower_string_no_digit_match():
    """Branch 171→166: parent text has no digits/spaces/commas — re.search returns None."""
    # We mock the soup to control exactly what get_text returns for a parent with 'follower' text.
    # The regex ([\d\s,]+) needs a string with zero digits, spaces, or commas to return None.
    # Using a string like "followers" (no digits) — but get_text() might add the child's space.
    # Safest: patch the parent's get_text to return a string with only letters, no [\d\s,].
    from unittest.mock import patch

    class FakeParent:
        def get_text(self, strip=False):
            # Return a string that matches \bfollower but has no digits/spaces/commas
            return "Nofollowers"

    class FakeNavigableString(str):
        parent = FakeParent()

    with patch("bs4.BeautifulSoup") as mock_bs:
        fake_soup = MagicMock()
        fake_soup.select_one.return_value = None
        fake_soup.find.return_value = None
        fake_soup.find_all.return_value = [FakeNavigableString("followers")]
        fake_soup.select.return_value = []
        mock_bs.return_value = fake_soup

        result = _parse_vk_html("<html><body><h1>User</h1></body></html>")

    # follower_count not set because regex didn't match
    assert "follower_count" not in result
