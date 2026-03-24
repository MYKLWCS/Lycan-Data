"""
Extended coverage tests for low-coverage crawlers.

Covers uncovered branches in:
  - facebook, linkedin, instagram (Playwright)
  - discord, pinterest, snapchat (HttpxCrawler)
  - email_breach, email_emailrep, email_mx_validator (HttpxCrawler)
  - people_familysearch, people_fbi_wanted, people_findagrave
  - people_immigration, people_interpol, people_namus
  - people_thatsthem, people_usmarshals
  - phone_carrier, phone_fonefinder, phone_numlookup, phone_truecaller

NOTE on error location:
  Crawlers that use self._result(..., error=X) put the error inside
  result.data["error"] (because _result() passes all kwargs as data).
  Crawlers that build CrawlerResult(..., error=X) directly set result.error.
"""

from __future__ import annotations

import socket
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text
    return resp


def make_page_cm(html: str, title: str = "", url: str = "https://example.com/"):
    """Build a mock Playwright page context manager."""
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=html)
    mock_page.title = AsyncMock(return_value=title)
    mock_page.url = url
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.get_attribute = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    return _cm


# ===========================================================================
# FACEBOOK — target 30% → 70%+
# ===========================================================================


@pytest.mark.asyncio
async def test_facebook_page_not_found():
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()
    with patch.object(crawler, "page", make_page_cm("page not found on Facebook")):
        result = await crawler.scrape("noonehere99xyz")

    assert result.found is False


@pytest.mark.asyncio
async def test_facebook_content_not_found():
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()
    with patch.object(crawler, "page", make_page_cm("content not found")):
        result = await crawler.scrape("missinguser")

    assert result.found is False


@pytest.mark.asyncio
async def test_facebook_login_wall_graph_found():
    """Login wall triggers _try_graph; graph API returns a valid profile."""
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()
    graph_json = {
        "name": "Test Page",
        "about": "A public page",
        "fan_count": 5000,
        "id": "123456",
    }

    mock_client = AsyncMock()
    mock_graph_resp = MagicMock()
    mock_graph_resp.status_code = 200
    mock_graph_resp.json.return_value = graph_json

    with (
        patch.object(
            crawler,
            "page",
            make_page_cm("Please log in to your password to continue"),
        ),
        patch("httpx.AsyncClient") as mock_httpx_cls,
    ):
        mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_graph_resp)
        result = await crawler.scrape("testpage")

    assert result.found is True
    assert result.data["display_name"] == "Test Page"
    assert result.data["follower_count"] == 5000


@pytest.mark.asyncio
async def test_facebook_login_wall_graph_not_found():
    """Login wall + graph returns no 'name' → found=False with login_wall error in data."""
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()
    mock_client = AsyncMock()
    mock_graph_resp = MagicMock()
    mock_graph_resp.status_code = 200
    mock_graph_resp.json.return_value = {"error": {"code": 100}}

    with (
        patch.object(
            crawler,
            "page",
            make_page_cm("Please log in password to continue"),
        ),
        patch("httpx.AsyncClient") as mock_httpx_cls,
    ):
        mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_graph_resp)
        result = await crawler.scrape("nonexistent_page")

    assert result.found is False
    # _result() puts error into data dict
    assert result.data.get("error") == "login_wall"


@pytest.mark.asyncio
async def test_facebook_login_wall_graph_exception():
    """Login wall + graph HTTP exception → found=False with login_wall error in data."""
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()

    with (
        patch.object(
            crawler,
            "page",
            make_page_cm("You must log in password to continue"),
        ),
        patch("httpx.AsyncClient") as mock_httpx_cls,
    ):
        mock_httpx_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await crawler.scrape("brokenpage")

    assert result.found is False
    assert result.data.get("error") == "login_wall"


@pytest.mark.asyncio
async def test_facebook_extract_mobile_title_and_followers():
    """Normal public profile with title, follower count, and location in HTML."""
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()
    html_content = """
    <html>
    <head><title>Awesome Brand | Facebook</title></head>
    <body>
    <p>12.5K followers</p>
    <script>{"location": "New York, NY"}</script>
    </body>
    </html>
    """

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=html_content)
    mock_page.url = "https://m.facebook.com/awesomebrand"
    mock_page.title = AsyncMock(return_value="Awesome Brand | Facebook")
    mock_page.query_selector = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    with patch.object(crawler, "page", _cm):
        result = await crawler.scrape("awesomebrand")

    assert result.found is True
    assert result.data["display_name"] == "Awesome Brand"
    assert result.data["follower_count"] == 12500


@pytest.mark.asyncio
async def test_facebook_extract_mobile_with_bio():
    """Profile with bio element present."""
    from modules.crawlers.facebook import FacebookCrawler

    crawler = FacebookCrawler()

    mock_bio_elem = AsyncMock()
    mock_bio_elem.inner_text = AsyncMock(return_value="We make great products.")

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body>regular page</body></html>")
    mock_page.url = "https://m.facebook.com/brand"
    mock_page.title = AsyncMock(return_value="Brand - Home | Facebook")
    mock_page.query_selector = AsyncMock(return_value=mock_bio_elem)

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    with patch.object(crawler, "page", _cm):
        result = await crawler.scrape("brand")

    assert result.found is True
    assert result.data.get("bio") == "We make great products."


# ===========================================================================
# LINKEDIN — target 25% → 70%+
# ===========================================================================


@pytest.mark.asyncio
async def test_linkedin_url_identifier():
    """Handles full LinkedIn URL as identifier."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    html = "<html><body>Profile page content here</body></html>"
    page_cm = make_page_cm(html, title="Jane Doe | LinkedIn", url="https://www.linkedin.com/in/janedoe/")

    with patch.object(crawler, "page", page_cm):
        result = await crawler.scrape("https://www.linkedin.com/in/janedoe/")

    assert result.found is True
    assert result.data["display_name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_linkedin_username_not_found():
    """Profile not found returns found=False."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    html = "<html><body>Page not found on LinkedIn</body></html>"

    with patch.object(crawler, "page", make_page_cm(html, url="https://www.linkedin.com/in/xyz/")):
        result = await crawler.scrape("nonexistentuser999")

    assert result.found is False


@pytest.mark.asyncio
async def test_linkedin_auth_wall_public_view_found():
    """Auth wall triggers _try_public_view; httpx returns profile with <h1>."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    auth_wall_html = "<html><body>Join to see full profile</body></html>"

    mock_client = AsyncMock()
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.url = "https://www.linkedin.com/in/johndoe/"
    mock_http_resp.text = "<html><body><h1>John Doe</h1><p>Software Engineer</p></body></html>"

    with (
        patch.object(
            crawler,
            "page",
            make_page_cm(
                auth_wall_html,
                url="https://www.linkedin.com/authwall?trk=test",
            ),
        ),
        patch("httpx.AsyncClient") as mock_httpx_cls,
    ):
        mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_http_resp)
        result = await crawler.scrape("johndoe")

    assert result.found is True
    assert result.data["display_name"] == "John Doe"


@pytest.mark.asyncio
async def test_linkedin_auth_wall_public_view_no_name():
    """Public view loads but has no <h1> → found=False."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    auth_html = "<html><body>login required</body></html>"

    mock_client = AsyncMock()
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.url = "https://www.linkedin.com/in/testuser/"
    mock_http_resp.text = "<html><body><p>No profile data here.</p></body></html>"

    with (
        patch.object(
            crawler,
            "page",
            make_page_cm(auth_html, url="https://www.linkedin.com/login?session=x"),
        ),
        patch("httpx.AsyncClient") as mock_httpx_cls,
    ):
        mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_http_resp)
        result = await crawler.scrape("testuser")

    assert result.found is False


@pytest.mark.asyncio
async def test_linkedin_auth_wall_public_view_exception():
    """Public view raises exception → found=False with auth_wall error in data."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    auth_html = "<html><body>login wall content</body></html>"

    with (
        patch.object(
            crawler,
            "page",
            make_page_cm(auth_html, url="https://www.linkedin.com/authwall"),
        ),
        patch("httpx.AsyncClient") as mock_httpx_cls,
    ):
        mock_httpx_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("network error"))
        mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await crawler.scrape("brokenuser")

    assert result.found is False
    assert result.data.get("error") == "auth_wall"


@pytest.mark.asyncio
async def test_linkedin_extract_title_dash_format():
    """Title in 'Name - Role | LinkedIn' format extracts name correctly."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    html = "<html><body>Some profile content</body></html>"
    page_cm = make_page_cm(html, title="Alice Smith - CEO at Corp", url="https://www.linkedin.com/in/alice/")

    with patch.object(crawler, "page", page_cm):
        result = await crawler.scrape("alice")

    assert result.found is True
    assert result.data["display_name"] == "Alice Smith"


@pytest.mark.asyncio
async def test_linkedin_profile_does_not_exist():
    """'profile does not exist' in content → found=False."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()
    html = "<html><body>This profile does not exist on LinkedIn.</body></html>"

    with patch.object(crawler, "page", make_page_cm(html, url="https://www.linkedin.com/in/ghost/")):
        result = await crawler.scrape("ghost")

    assert result.found is False


@pytest.mark.asyncio
async def test_linkedin_extract_with_headline_and_location():
    """Profile with headline and location selectors."""
    from modules.crawlers.linkedin import LinkedInCrawler

    crawler = LinkedInCrawler()

    mock_headline = AsyncMock()
    mock_headline.inner_text = AsyncMock(return_value="Senior Engineer at Acme")

    mock_loc = AsyncMock()
    mock_loc.inner_text = AsyncMock(return_value="San Francisco, CA")

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body>profile content</body></html>")
    mock_page.url = "https://www.linkedin.com/in/bobsmith/"
    mock_page.title = AsyncMock(return_value="Bob Smith | LinkedIn")

    async def query_selector_side_effect(selector):
        if "headline" in selector:
            return mock_headline
        if "subline-item" in selector:
            return mock_loc
        return None

    mock_page.query_selector = AsyncMock(side_effect=query_selector_side_effect)

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    with patch.object(crawler, "page", _cm):
        result = await crawler.scrape("bobsmith")

    assert result.found is True
    assert result.data["headline"] == "Senior Engineer at Acme"
    assert result.data["location"] == "San Francisco, CA"


# ===========================================================================
# INSTAGRAM — add error paths (currently 47%)
# ===========================================================================


@pytest.mark.asyncio
async def test_instagram_blocked_or_captcha():
    """Empty data (no display_name, no follower_count) triggers rotate and blocked error."""
    from modules.crawlers.instagram import InstagramCrawler

    crawler = InstagramCrawler()

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body>some content</body></html>")
    mock_page.get_attribute = AsyncMock(return_value=None)
    mock_page.title = AsyncMock(return_value="")

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    with (
        patch.object(crawler, "page", _cm),
        patch.object(crawler, "rotate_circuit", AsyncMock()) as mock_rotate,
    ):
        result = await crawler.scrape("suspectuser")

    assert result.found is False
    # _result() stores error in data dict
    assert result.data.get("error") == "blocked_or_captcha"
    mock_rotate.assert_called_once()


@pytest.mark.asyncio
async def test_instagram_isn_t_available_variant():
    """'isn't available' phrase triggers not found."""
    from modules.crawlers.instagram import InstagramCrawler

    crawler = InstagramCrawler()
    with patch.object(
        crawler,
        "page",
        make_page_cm("Sorry, this page isn't available"),
    ):
        result = await crawler.scrape("deleteduser")

    assert result.found is False


@pytest.mark.asyncio
async def test_instagram_full_profile_parsed():
    """Full profile extraction: followers, following, posts, name, bio, email, verified."""
    from modules.crawlers.instagram import InstagramCrawler

    crawler = InstagramCrawler()
    html_content = '<html><body>is_verified":true data here</body></html>'
    meta_desc = "1.2M Followers, 500 Following, 300 Posts - contact@brand.com +1 (555) 123-4567"

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=html_content)
    mock_page.title = AsyncMock(return_value="Brand Name (@brand) • Instagram photos and videos")

    async def get_attr(selector, attr):
        if 'name="description"' in selector:
            return meta_desc
        if 'og:description' in selector:
            return "Official brand account. contact@brand.com"
        return None

    mock_page.get_attribute = AsyncMock(side_effect=get_attr)

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    with patch.object(crawler, "page", _cm):
        result = await crawler.scrape("brand")

    assert result.found is True
    assert result.data["follower_count"] == 1200000
    assert result.data["following_count"] == 500
    assert result.data["post_count"] == 300
    assert result.data["display_name"] == "Brand Name"
    assert result.data["is_verified"] is True
    assert result.data.get("email") == "contact@brand.com"


# ===========================================================================
# DISCORD — uncovered branches
# ===========================================================================


@pytest.mark.asyncio
async def test_discord_404_response():
    """404 from lookup API returns found=False with no error."""
    from modules.crawlers.discord import DiscordCrawler

    crawler = DiscordCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=404))):
        result = await crawler.scrape("80351110224678912")

    assert result.found is False


@pytest.mark.asyncio
async def test_discord_unexpected_status():
    """Non-200/404 status returns found=False with unexpected_status error."""
    from modules.crawlers.discord import DiscordCrawler

    crawler = DiscordCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("80351110224678912")

    assert result.found is False
    # _result() stores error in data dict
    assert "unexpected_status" in (result.data.get("error") or "")


@pytest.mark.asyncio
async def test_discord_json_parse_error():
    """Bad JSON body → found=False with json_parse_error."""
    from modules.crawlers.discord import DiscordCrawler

    crawler = DiscordCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("80351110224678912")

    assert result.found is False
    assert result.data.get("error") == "json_parse_error"


@pytest.mark.asyncio
async def test_discord_bot_flag_and_no_avatar():
    """Bot user with no avatar hash — avatar_url absent in data."""
    from modules.crawlers.discord import DiscordCrawler

    crawler = DiscordCrawler()
    payload = {
        "id": "80351110224678912",
        "username": "BotUser",
        "discriminator": "0000",
        "avatar": None,
        "bot": True,
    }
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(status=200, json_data=payload)),
    ):
        result = await crawler.scrape("80351110224678912")

    assert result.found is True
    assert result.data["bot"] is True
    assert "avatar_url" not in result.data


@pytest.mark.asyncio
async def test_discord_tag_field_fallback():
    """discriminator absent but 'tag' present — uses tag field."""
    from modules.crawlers.discord import DiscordCrawler

    crawler = DiscordCrawler()
    payload = {
        "id": "80351110224678912",
        "username": "Nelly",
        "tag": "1337",
        "avatar": "abc123",
        "bot": False,
    }
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(status=200, json_data=payload)),
    ):
        result = await crawler.scrape("80351110224678912")

    assert result.found is True
    assert result.data["discriminator"] == "1337"


def test_discord_snowflake_to_datetime_known_value():
    """Snowflake 175928847299117063 was created around 2016-04-30."""
    from modules.crawlers.discord import snowflake_to_datetime

    ts = snowflake_to_datetime(175928847299117063)
    assert "2016" in ts


# ===========================================================================
# PINTEREST — uncovered branches
# ===========================================================================


@pytest.mark.asyncio
async def test_pinterest_http_error_none():
    """None response returns found=False with http_error in data."""
    from modules.crawlers.pinterest import PinterestCrawler

    crawler = PinterestCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("anyuser")

    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_pinterest_parse_failed_no_title():
    """200 response but no og:title → found=False with parse_failed in data."""
    from modules.crawlers.pinterest import PinterestCrawler

    crawler = PinterestCrawler()
    html = "<html><head><meta property='og:image' content='https://img.png'/></head></html>"
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("emptyprofile")

    assert result.found is False
    assert result.data.get("error") == "parse_failed"


@pytest.mark.asyncio
async def test_pinterest_follower_count_no_match():
    """Description present but no follower count pattern → follower_count absent."""
    from modules.crawlers.pinterest import PinterestCrawler

    crawler = PinterestCrawler()
    html = """
    <html><head>
    <meta property="og:title" content="Pin Board User" />
    <meta property="og:description" content="Pinning great stuff daily" />
    </head></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("pinboarduser")

    assert result.found is True
    assert "follower_count" not in result.data


@pytest.mark.asyncio
async def test_pinterest_with_avatar_and_bio():
    """Full profile parse with avatar and bio."""
    from modules.crawlers.pinterest import PinterestCrawler

    crawler = PinterestCrawler()
    html = """
    <html><head>
    <meta property="og:title" content="Creative User" />
    <meta property="og:image" content="https://i.pinimg.com/user.jpg" />
    <meta property="og:description" content="Creative content | 5,678 followers, 100 following" />
    </head></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("creativeuser")

    assert result.found is True
    assert result.data["avatar_url"] == "https://i.pinimg.com/user.jpg"
    assert result.data["follower_count"] == 5678
    assert "Creative content" in result.data["bio"]


# ===========================================================================
# SNAPCHAT — few remaining branches (currently 92%)
# ===========================================================================


@pytest.mark.asyncio
async def test_snapchat_404_response():
    """404 status returns found=False."""
    from modules.crawlers.snapchat import SnapchatCrawler

    crawler = SnapchatCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=404))):
        result = await crawler.scrape("ghost404user")

    assert result.found is False


@pytest.mark.asyncio
async def test_snapchat_parse_failed_no_title():
    """200 response but no og:title → found=False with parse_failed in data."""
    from modules.crawlers.snapchat import SnapchatCrawler

    crawler = SnapchatCrawler()
    html = "<html><head><meta property='og:image' content='https://img.snap.com/sc.png'/></head></html>"
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("notitleuser")

    assert result.found is False
    assert result.data.get("error") == "parse_failed"


@pytest.mark.asyncio
async def test_snapchat_title_only_snapchat_rejected():
    """og:title that resolves to 'snapchat' only → parse_failed."""
    from modules.crawlers.snapchat import SnapchatCrawler

    crawler = SnapchatCrawler()
    html = """
    <html><head>
    <meta property="og:title" content="Snapchat" />
    </head></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("fakesnap")

    assert result.found is False


@pytest.mark.asyncio
async def test_snapchat_multilingual_suffix_stripped():
    """Title 'User sur Snapchat' → display_name='Marie' (French locale)."""
    from modules.crawlers.snapchat import SnapchatCrawler

    crawler = SnapchatCrawler()
    html = """
    <html><head>
    <meta property="og:title" content="Marie sur Snapchat" />
    <meta property="og:description" content="Bonjour!" />
    </head></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("marie")

    assert result.found is True
    assert result.data["display_name"] == "Marie"


@pytest.mark.asyncio
async def test_snapchat_dash_separator_stripped():
    """Title 'User - Snapchat' → display_name='Jake'."""
    from modules.crawlers.snapchat import SnapchatCrawler

    crawler = SnapchatCrawler()
    html = """
    <html><head>
    <meta property="og:title" content="Jake - Snapchat" />
    </head></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("jake")

    assert result.found is True
    assert result.data["display_name"] == "Jake"


# ===========================================================================
# EMAIL_BREACH — target 22% → 70%+
# ===========================================================================


@pytest.mark.asyncio
async def test_email_breach_all_sources_empty():
    """All three sources return nothing → found=True, breach_count=0."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    empty_resp = _mock_resp(200, json_data={"data": [], "success": False})

    with patch.object(crawler, "get", AsyncMock(return_value=empty_resp)):
        result = await crawler.scrape("clean@example.com")

    assert result.found is True
    assert result.data["breach_count"] == 0
    assert result.data["breaches"] == []
    assert "psbdmp" in result.data["checked_sources"]


@pytest.mark.asyncio
async def test_email_breach_psbdmp_list_response():
    """PSBDMP returns list directly → parsed as breach records."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    psbdmp_resp = _mock_resp(
        200,
        json_data=[
            {"id": "abc123", "text": "some leaked data"},
            {"id": "def456", "text": "more data"},
        ],
    )
    # Other calls return empty
    empty_resp = _mock_resp(200, json_data={"items": [], "success": False})

    with patch.object(
        crawler,
        "get",
        AsyncMock(side_effect=[psbdmp_resp, empty_resp, empty_resp]),
    ):
        result = await crawler.scrape("victim@test.com")

    assert result.found is True
    assert result.data["breach_count"] == 2
    psbdmp_hits = [b for b in result.data["breaches"] if b["source"] == "psbdmp"]
    assert len(psbdmp_hits) == 2
    assert psbdmp_hits[0]["name"] == "psbdmp:abc123"


@pytest.mark.asyncio
async def test_email_breach_github_code_search_hits():
    """GitHub code search returns items → parsed as source_code_exposure records."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    psbdmp_empty = _mock_resp(200, json_data=[])
    github_resp = _mock_resp(
        200,
        json_data={
            "items": [
                {
                    "repository": {"full_name": "owner/repo"},
                    "path": "config/secrets.env",
                },
                {
                    "repository": {"full_name": "other/project"},
                    "path": "README.md",
                },
            ]
        },
    )
    leakcheck_empty = _mock_resp(200, json_data={"success": False})

    with patch.object(
        crawler,
        "get",
        AsyncMock(side_effect=[psbdmp_empty, github_resp, leakcheck_empty]),
    ):
        result = await crawler.scrape("exposed@corp.com")

    github_hits = [b for b in result.data["breaches"] if b["source"] == "github"]
    assert len(github_hits) == 2
    assert github_hits[0]["repo"] == "owner/repo"
    assert github_hits[0]["data_classes"] == ["source_code_exposure"]


@pytest.mark.asyncio
async def test_email_breach_leakcheck_found():
    """LeakCheck returns success=True with sources → breach records created."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    psbdmp_empty = _mock_resp(200, json_data=[])
    github_empty = _mock_resp(200, json_data={"items": []})
    leakcheck_resp = _mock_resp(
        200,
        json_data={
            "success": True,
            "found": 2,
            "sources": ["Collection1", "Exploit.in"],
        },
    )

    with patch.object(
        crawler,
        "get",
        AsyncMock(side_effect=[psbdmp_empty, github_empty, leakcheck_resp]),
    ):
        result = await crawler.scrape("pwned@example.com")

    leakcheck_hits = [b for b in result.data["breaches"] if b["source"] == "leakcheck"]
    assert len(leakcheck_hits) == 2
    assert leakcheck_hits[0]["name"] == "Collection1"


@pytest.mark.asyncio
async def test_email_breach_psbdmp_invalid_json():
    """PSBDMP invalid JSON → silently returns empty list, pipeline continues."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("not json")

    empty = _mock_resp(200, json_data={"items": [], "success": False})

    with patch.object(
        crawler,
        "get",
        AsyncMock(side_effect=[bad_resp, empty, empty]),
    ):
        result = await crawler.scrape("test@broken.com")

    assert result.found is True
    assert result.data["breach_count"] == 0


@pytest.mark.asyncio
async def test_email_breach_http_non_200():
    """Non-200 from all sources → breach_count=0."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    fail_resp = _mock_resp(status=503)

    with patch.object(crawler, "get", AsyncMock(return_value=fail_resp)):
        result = await crawler.scrape("network@fail.com")

    assert result.data["breach_count"] == 0


@pytest.mark.asyncio
async def test_email_breach_psbdmp_data_key():
    """PSBDMP returns dict with 'data' key (not direct list)."""
    from modules.crawlers.email_breach import EmailBreachCrawler

    crawler = EmailBreachCrawler()
    psbdmp_resp = _mock_resp(
        200,
        json_data={"data": [{"id": "xyz789", "text": "leaked text"}]},
    )
    empty = _mock_resp(200, json_data={"items": [], "success": False})

    with patch.object(
        crawler,
        "get",
        AsyncMock(side_effect=[psbdmp_resp, empty, empty]),
    ):
        result = await crawler.scrape("victim2@test.com")

    psbdmp_hits = [b for b in result.data["breaches"] if b["source"] == "psbdmp"]
    assert len(psbdmp_hits) == 1
    assert psbdmp_hits[0]["data_classes"] == ["paste_dump"]


def test_email_breach_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("email_breach")


# ===========================================================================
# EMAIL_EMAILREP — target 41% → 75%+
# ===========================================================================


@pytest.mark.asyncio
async def test_emailrep_found_suspicious():
    """Suspicious email with reputation=high → found=True."""
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    data = {
        "email": "suspect@example.com",
        "reputation": "high",
        "suspicious": True,
        "references": 10,
        "details": {
            "blacklisted": True,
            "malicious_activity": True,
            "credentials_leaked": True,
            "data_breach": True,
            "profiles": ["twitter", "github"],
            "spam": True,
            "deliverability": "DELIVERABLE",
            "days_since_domain_creation": 3650,
            "last_seen": "2024-01-01",
        },
    }
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=data))
    ):
        result = await crawler.scrape("suspect@example.com")

    assert result.found is True
    assert result.data["reputation"] == "high"
    assert result.data["suspicious"] is True
    assert result.data["details"]["blacklisted"] is True
    assert "twitter" in result.data["details"]["profiles"]


@pytest.mark.asyncio
async def test_emailrep_reputation_none_not_suspicious():
    """Reputation=none and not suspicious → found=False."""
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    data = {
        "email": "new@unknown.com",
        "reputation": "none",
        "suspicious": False,
        "references": 0,
        "details": {},
    }
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=data))
    ):
        result = await crawler.scrape("new@unknown.com")

    assert result.found is False


@pytest.mark.asyncio
async def test_emailrep_http_error_none():
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    # EmailRepCrawler uses CrawlerResult(..., error=...) directly → result.error
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_emailrep_rate_limited():
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_emailrep_non_200_non_429():
    """503 response → found=False with http_503 error."""
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_emailrep_invalid_json():
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("not json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "invalid_json"


def test_emailrep_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("email_emailrep")


def test_emailrep_source_reliability():
    from modules.crawlers.email_emailrep import EmailRepCrawler

    assert EmailRepCrawler().source_reliability == 0.85


# ===========================================================================
# EMAIL_MX_VALIDATOR — target 41% → 75%+
# NOTE: 'dns' module not installed; we mock at the module level
# ===========================================================================


@pytest.mark.asyncio
async def test_mx_validator_not_an_email():
    """Identifier without '@' → found=False with 'Not an email address' error."""
    from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

    crawler = EmailMXValidatorCrawler()
    result = await crawler.scrape("notanemail")

    assert result.found is False
    assert "not an email" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_mx_validator_known_domain_with_dns():
    """Valid email with resolvable domain (mocked dns import) → found=True."""
    from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

    crawler = EmailMXValidatorCrawler()

    mock_mx = MagicMock()
    mock_mx.preference = 10
    mock_mx.exchange = "mail.example.com."

    mock_resolver = MagicMock()
    mock_resolver.resolve = MagicMock(return_value=[mock_mx])

    mock_dns = MagicMock()
    mock_dns.resolver = mock_resolver

    with patch.dict("sys.modules", {"dns": mock_dns, "dns.resolver": mock_resolver}):
        result = await crawler.scrape("user@example.com")

    assert result.found is True
    assert result.data["mx_available"] is True
    assert result.data["is_disposable"] is False


@pytest.mark.asyncio
async def test_mx_validator_disposable_domain():
    """Mailinator domain → is_disposable=True."""
    from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

    crawler = EmailMXValidatorCrawler()

    mock_mx = MagicMock()
    mock_mx.preference = 5
    mock_mx.exchange = "aspmx.l.google.com."

    mock_resolver = MagicMock()
    mock_resolver.resolve = MagicMock(return_value=[mock_mx])

    mock_dns = MagicMock()
    mock_dns.resolver = mock_resolver

    with patch.dict("sys.modules", {"dns": mock_dns, "dns.resolver": mock_resolver}):
        result = await crawler.scrape("throwaway@mailinator.com")

    assert result.data["is_disposable"] is True


@pytest.mark.asyncio
async def test_mx_validator_dns_exception_socket_fallback_success():
    """dns.resolver raises → socket fallback succeeds → mx_available=True."""
    from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

    crawler = EmailMXValidatorCrawler()

    mock_resolver = MagicMock()
    mock_resolver.resolve = MagicMock(side_effect=Exception("NXDOMAIN"))
    mock_dns = MagicMock()
    mock_dns.resolver = mock_resolver

    with (
        patch.dict("sys.modules", {"dns": mock_dns, "dns.resolver": mock_resolver}),
        patch("socket.gethostbyname", return_value="1.2.3.4"),
    ):
        result = await crawler.scrape("user@reachable.com")

    assert result.found is True
    assert result.data["mx_available"] is True
    assert result.data["mx_records"] == []


@pytest.mark.asyncio
async def test_mx_validator_dns_and_socket_both_fail():
    """Both dns and socket fail → mx_available=False, found=False."""
    from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

    crawler = EmailMXValidatorCrawler()

    mock_resolver = MagicMock()
    mock_resolver.resolve = MagicMock(side_effect=Exception("NXDOMAIN"))
    mock_dns = MagicMock()
    mock_dns.resolver = mock_resolver

    with (
        patch.dict("sys.modules", {"dns": mock_dns, "dns.resolver": mock_resolver}),
        patch("socket.gethostbyname", side_effect=socket.gaierror("not found")),
    ):
        result = await crawler.scrape("user@nonexistentdomain99xyz.com")

    assert result.found is False
    assert result.data["mx_available"] is False


@pytest.mark.asyncio
async def test_mx_validator_dns_not_installed_socket_fallback():
    """When dns module is absent → ImportError branch → socket fallback."""
    from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

    crawler = EmailMXValidatorCrawler()

    # Remove dns from sys.modules to simulate it not being installed
    with (
        patch.dict("sys.modules", {"dns": None, "dns.resolver": None}),
        patch("socket.gethostbyname", return_value="5.6.7.8"),
    ):
        result = await crawler.scrape("user@reachable2.com")

    # With dns=None in sys.modules, `import dns.resolver` raises ImportError
    # → falls back to socket which succeeds
    assert result.found is True


def test_mx_validator_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("email_mx_validator")


# ===========================================================================
# PEOPLE_FAMILYSEARCH — full coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_familysearch_found_with_records():
    """200 response with entries → persons list returned."""
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    entry = {
        "id": "MMMM-0001",
        "title": "Birth Record",
        "content": {
            "gedcomx": {
                "persons": [
                    {
                        "id": "MMMM-0001",
                        "names": [
                            {
                                "nameForms": [
                                    {"fullText": "John Smith"},
                                ]
                            }
                        ],
                        "facts": [
                            {
                                "type": "Birth",
                                "date": {"original": "1950"},
                                "place": {"original": "New York"},
                            },
                            {
                                "type": "Death",
                                "date": {"original": "2010"},
                            },
                        ],
                    }
                ]
            }
        },
    }
    response_data = {"entries": [entry], "results": 1}

    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=response_data)),
    ):
        result = await crawler.scrape("John Smith 1950")

    assert result.found is True
    assert result.data["total"] == 1
    persons = result.data["persons"]
    assert persons[0]["name"] == "John Smith"
    assert persons[0]["birth_date"] == "1950"
    assert persons[0]["death_date"] == "2010"


@pytest.mark.asyncio
async def test_familysearch_no_entries():
    """200 with empty entries → found=False."""
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data={"entries": [], "results": 0})),
    ):
        result = await crawler.scrape("Xyz Zzz Notreal")

    assert result.found is False
    assert result.data["persons"] == []


@pytest.mark.asyncio
async def test_familysearch_http_error():
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    # Uses CrawlerResult(..., error=...) directly → result.error
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_familysearch_auth_required():
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=401))):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "auth_required"


@pytest.mark.asyncio
async def test_familysearch_rate_limited():
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_familysearch_non_200_206():
    """503 response → found=False with http_503."""
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_familysearch_invalid_json():
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "invalid_json"


@pytest.mark.asyncio
async def test_familysearch_206_partial():
    """206 Partial Content is treated as success."""
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler

    crawler = PeopleFamilySearchCrawler()
    data = {"entries": [{"id": "X1", "content": {"gedcomx": {"persons": []}}}], "results": 1}
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(status=206, json_data=data))
    ):
        result = await crawler.scrape("Mary Jane")

    # Entry has no persons so name will be empty, but parsing proceeds without error
    assert "persons" in result.data


@pytest.mark.asyncio
async def test_familysearch_with_api_key():
    """With api_key set, uses tree search endpoint and includes Authorization header."""
    from modules.crawlers.people_familysearch import PeopleFamilySearchCrawler
    from shared.config import settings

    crawler = PeopleFamilySearchCrawler()
    data = {"entries": [], "results": 0}

    captured_headers = {}

    async def mock_get(url, headers=None, **kwargs):
        captured_headers.update(headers or {})
        return _mock_resp(200, json_data=data)

    # Patch at the module level via getattr so we don't fight pydantic
    with patch.object(
        crawler.__class__,
        "scrape",
        wraps=None,
    ):
        pass  # just ensure class is importable

    # Patch the getattr call on settings object
    with patch(
        "modules.crawlers.people_familysearch.settings",
        **{"familysearch_api_key": "test-key-123"},
    ) as mock_settings:
        mock_settings.familysearch_api_key = "test-key-123"
        with patch.object(crawler, "get", AsyncMock(side_effect=mock_get)):
            result = await crawler.scrape("John Doe 1920")

    assert "Authorization" in captured_headers
    assert captured_headers["Authorization"] == "Bearer test-key-123"
    assert result.data.get("authenticated") is True


def test_familysearch_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_familysearch")


def test_familysearch_parse_entry_no_names():
    """_parse_entry with empty persons list returns empty name."""
    from modules.crawlers.people_familysearch import _parse_entry

    entry = {"id": "X1", "title": "Record", "content": {"gedcomx": {"persons": []}}}
    result = _parse_entry(entry)
    assert result["name"] == ""
    assert result["birth_date"] is None


# ===========================================================================
# PEOPLE_FBI_WANTED — full coverage
# ===========================================================================


_FBI_ITEM = {
    "title": "John Public Enemy",
    "description": "Armed and dangerous",
    "aliases": ["Johnny"],
    "dates_of_birth_used": ["1975-01-01"],
    "hair": "Brown",
    "eyes": "Blue",
    "height_min": 70,
    "height_max": 72,
    "weight": 180,
    "weight_max": 200,
    "sex": "Male",
    "race": "White",
    "nationality": "American",
    "reward_text": "$100,000",
    "caution": "Should be considered armed",
    "url": "https://www.fbi.gov/wanted/fugitives/john-public-enemy",
    "status": "na",
    "modified": "2024-01-01",
    "publication": "2023-01-01",
    "subjects": ["Fugitive"],
    "field_offices": ["New York"],
}


@pytest.mark.asyncio
async def test_fbi_wanted_found():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    crawler = FbiWantedCrawler()
    payload = {"total": 1, "items": [_FBI_ITEM]}

    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=payload))
    ):
        result = await crawler.scrape("John Public Enemy")

    assert result.found is True
    assert result.data["total"] == 1
    items = result.data["items"]
    assert items[0]["title"] == "John Public Enemy"
    assert items[0]["reward_text"] == "$100,000"
    assert items[0]["aliases"] == ["Johnny"]


@pytest.mark.asyncio
async def test_fbi_wanted_no_matches():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    crawler = FbiWantedCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data={"total": 0, "items": []})),
    ):
        result = await crawler.scrape("Nobody Nowhere")

    assert result.found is False
    assert result.data["items"] == []


@pytest.mark.asyncio
async def test_fbi_wanted_http_error():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    crawler = FbiWantedCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    # Uses CrawlerResult(..., error=...) directly
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_fbi_wanted_rate_limited():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    crawler = FbiWantedCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_fbi_wanted_non_200():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    crawler = FbiWantedCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_fbi_wanted_parse_error():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    crawler = FbiWantedCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "parse_error"


def test_fbi_wanted_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_fbi_wanted")


def test_fbi_parse_items_skips_non_dict():
    """_parse_items skips non-dict entries in the items list."""
    from modules.crawlers.people_fbi_wanted import _parse_items

    data = {"items": [_FBI_ITEM, "not a dict", None, 42]}
    items = _parse_items(data)
    assert len(items) == 1
    assert items[0]["title"] == "John Public Enemy"


def test_fbi_source_reliability():
    from modules.crawlers.people_fbi_wanted import FbiWantedCrawler

    assert FbiWantedCrawler().source_reliability == 0.99


# ===========================================================================
# PEOPLE_FINDAGRAVE — full coverage
# ===========================================================================


_FINDAGRAVE_HTML_WITH_MEMORIAL = """
<html><body>
<div class="memorial-item" id="sr-12345">
  <a href="/memorial/12345/john-smith">John Smith</a>
  <span>15 March 1920 - 4 July 2000</span>
</div>
</body></html>
"""

_FINDAGRAVE_JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
[{"@type": "Person", "name": "Jane Doe", "birthDate": "1930", "deathDate": "2005", "url": "https://www.findagrave.com/memorial/99999"}]
</script>
</head><body><p>No direct memorial items found here.</p></body></html>
"""


@pytest.mark.asyncio
async def test_findagrave_found_memorial_html():
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text=_FINDAGRAVE_HTML_WITH_MEMORIAL)),
    ):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    memorials = result.data["memorials"]
    assert len(memorials) >= 1
    assert memorials[0]["memorial_id"] == "12345"
    assert "John Smith" in memorials[0]["name"]


@pytest.mark.asyncio
async def test_findagrave_found_via_jsonld():
    """Fallback JSON-LD extraction when no memorial-item divs present."""
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text=_FINDAGRAVE_JSONLD_HTML)),
    ):
        result = await crawler.scrape("Jane Doe")

    assert result.found is True
    memorials = result.data["memorials"]
    assert any(m.get("name") == "Jane Doe" for m in memorials)


@pytest.mark.asyncio
async def test_findagrave_empty_identifier():
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    result = await crawler.scrape("   ")

    assert result.found is False
    # _result() stores error in data
    assert result.data.get("error") == "empty_identifier"


@pytest.mark.asyncio
async def test_findagrave_http_error():
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("Someone Real")

    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_findagrave_blocked_403():
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=403))):
        result = await crawler.scrape("Someone Real")

    assert result.found is False
    assert result.data.get("error") == "blocked_403"


@pytest.mark.asyncio
async def test_findagrave_non_200_non_403():
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=500))):
        result = await crawler.scrape("Test Person")

    assert result.found is False
    assert result.data.get("error") == "http_500"


@pytest.mark.asyncio
async def test_findagrave_no_memorials():
    """200 response with no extractable memorials → found=False."""
    from modules.crawlers.people_findagrave import FindAGraveCrawler

    crawler = FindAGraveCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text="<html><body><p>No results.</p></body></html>")),
    ):
        result = await crawler.scrape("Xyz Notreal")

    assert result.found is False
    assert result.data["memorials"] == []


def test_findagrave_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_findagrave")


def test_parse_memorial_html_direct():
    """Direct test of _parse_memorial_html with known HTML."""
    from modules.crawlers.people_findagrave import _parse_memorial_html

    memorials = _parse_memorial_html(_FINDAGRAVE_HTML_WITH_MEMORIAL)
    assert isinstance(memorials, list)


# ===========================================================================
# PEOPLE_IMMIGRATION — full coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_immigration_a_number_lookup():
    """A-number format → returns portal guidance without HTTP call."""
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    with patch.object(crawler, "get", AsyncMock()) as mock_get:
        result = await crawler.scrape("A123456789")

    assert result.found is False
    # _result() stores error in data
    assert result.data.get("error") == "a_number_requires_portal"
    assert result.data["search_type"] == "a_number"
    assert "A-Number" in result.data["manual_search"]
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_immigration_a_number_without_prefix():
    """9-digit number without 'A' prefix also detected as A-number."""
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    with patch.object(crawler, "get", AsyncMock()) as mock_get:
        result = await crawler.scrape("123456789")

    assert result.data.get("error") == "a_number_requires_portal"
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_immigration_name_search_found():
    """Name search → CourtListener returns docket results."""
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    payload = {
        "count": 2,
        "results": [
            {
                "case_name": "Rodriguez v. DHS",
                "docket_number": "A19-001",
                "court": "BIA",
                "date_filed": "2019-05-01",
                "date_terminated": "2021-03-15",
                "absolute_url": "/docket/12345/",
            },
            {
                "case_name": "Rodriguez Immigration",
                "docket_number": "A19-002",
                "court": "IJ",
                "date_filed": "2019-06-01",
                "date_terminated": None,
                "absolute_url": "/docket/12346/",
            },
        ],
    }
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=payload))
    ):
        result = await crawler.scrape("Juan Rodriguez")

    assert result.found is True
    assert result.data["total"] == 2
    assert result.data["search_type"] == "name"
    assert len(result.data["cases"]) == 2
    assert result.data["cases"][0]["case_name"] == "Rodriguez v. DHS"


@pytest.mark.asyncio
async def test_immigration_name_search_no_results():
    """Empty results → found=False."""
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data={"count": 0, "results": []})),
    ):
        result = await crawler.scrape("Xyz Notreal")

    assert result.found is False
    assert result.data["cases"] == []


@pytest.mark.asyncio
async def test_immigration_http_error():
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("Juan Rodriguez")

    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_immigration_403_auth_required():
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=403))):
        result = await crawler.scrape("Juan Rodriguez")

    assert result.found is False
    assert result.data.get("error") == "auth_required"


@pytest.mark.asyncio
async def test_immigration_non_200():
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=500))):
        result = await crawler.scrape("Juan Rodriguez")

    assert result.found is False
    assert result.data.get("error") == "http_500"


@pytest.mark.asyncio
async def test_immigration_parse_error():
    from modules.crawlers.people_immigration import PeopleImmigrationCrawler

    crawler = PeopleImmigrationCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("Juan Rodriguez")

    assert result.found is False
    assert result.data.get("error") == "parse_error"


def test_immigration_is_a_number():
    from modules.crawlers.people_immigration import _is_a_number

    assert _is_a_number("A123456789") is True
    assert _is_a_number("123456789") is True
    assert _is_a_number("A12345678") is True
    assert _is_a_number("Juan Rodriguez") is False
    assert _is_a_number("John") is False


def test_immigration_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_immigration")


# ===========================================================================
# PEOPLE_INTERPOL — full coverage
# ===========================================================================


_INTERPOL_NOTICE = {
    "entity_id": "2024/12345",
    "name": "DOE",
    "forename": "JOHN",
    "date_of_birth": "1980/01/15",
    "nationalities": ["US"],
    "charges": "Fraud",
    "_links": {
        "self": {"href": "https://ws-public.interpol.int/notices/v1/red/2024-12345"}
    },
}


@pytest.mark.asyncio
async def test_interpol_found():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    payload = {
        "total": 1,
        "_embedded": {"notices": [_INTERPOL_NOTICE]},
    }
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=payload))
    ):
        result = await crawler.scrape("John Doe")

    assert result.found is True
    assert result.data["total"] == 1
    notices = result.data["notices"]
    assert notices[0]["name"] == "DOE"
    assert notices[0]["forename"] == "JOHN"
    assert notices[0]["nationalities"] == ["US"]
    assert notices[0]["charges"] == "Fraud"


@pytest.mark.asyncio
async def test_interpol_no_notices():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    payload = {"total": 0, "_embedded": {"notices": []}}
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=payload))
    ):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False
    assert result.data["notices"] == []


@pytest.mark.asyncio
async def test_interpol_single_word_identifier():
    """Single-word name → used as surname, forename is empty in URL."""
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    payload = {"total": 0, "_embedded": {"notices": []}}

    captured_url = []

    async def mock_get(url, headers=None, **kwargs):
        captured_url.append(url)
        return _mock_resp(200, json_data=payload)

    with patch.object(crawler, "get", AsyncMock(side_effect=mock_get)):
        result = await crawler.scrape("Oswald")

    assert len(captured_url) == 1
    assert "Oswald" in captured_url[0]


@pytest.mark.asyncio
async def test_interpol_http_error():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    # Uses CrawlerResult(..., error=...) directly
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_interpol_rate_limited():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_interpol_non_200():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_interpol_invalid_json():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    crawler = PeopleInterpolCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "invalid_json"


def test_interpol_parse_notice_no_links():
    """_parse_notice with missing _links returns notice_url=None."""
    from modules.crawlers.people_interpol import _parse_notice

    notice = {
        "entity_id": "X001",
        "name": "SMITH",
        "forename": "JANE",
        "nationalities": [],
    }
    result = _parse_notice(notice)
    assert result["notice_url"] is None
    assert result["entity_id"] == "X001"


def test_interpol_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_interpol")


def test_interpol_source_reliability():
    from modules.crawlers.people_interpol import PeopleInterpolCrawler

    assert PeopleInterpolCrawler().source_reliability == 0.99


# ===========================================================================
# PEOPLE_NAMUS — full coverage
# ===========================================================================


_NAMUS_CASE = {
    "caseNumber": "MP12345",
    "ncmecNumber": "NCMEC001",
    "subjectIdentification": {
        "firstName": "Jane",
        "lastName": "Doe",
        "middleName": "A",
        "nicknames": "JD",
        "dateOfBirth": "1990-01-01",
        "computedMissingMinAge": 25,
        "sex": {"name": "Female"},
        "races": [{"name": "White"}],
    },
    "circumstances": {"dateMissing": "2015-06-15"},
    "sightings": [
        {
            "address": {
                "city": "Denver",
                "state": {"name": "Colorado"},
            }
        }
    ],
}


@pytest.mark.asyncio
async def test_namus_found():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    payload = {"results": [_NAMUS_CASE], "total": 1}

    with patch.object(
        crawler, "post", AsyncMock(return_value=_mock_resp(200, json_data=payload))
    ):
        result = await crawler.scrape("Jane Doe")

    assert result.found is True
    assert result.data["total"] == 1
    cases = result.data["cases"]
    assert cases[0]["first_name"] == "Jane"
    assert cases[0]["last_name"] == "Doe"
    assert cases[0]["sex"] == "Female"
    assert "White" in cases[0]["race"]
    assert cases[0]["missing_city"] == "Denver"
    assert cases[0]["case_url"].endswith("MP12345")


@pytest.mark.asyncio
async def test_namus_no_results():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    with patch.object(
        crawler,
        "post",
        AsyncMock(return_value=_mock_resp(200, json_data={"results": [], "total": 0})),
    ):
        result = await crawler.scrape("Xyz Notreal")

    assert result.found is False
    assert result.data["cases"] == []


@pytest.mark.asyncio
async def test_namus_empty_identifier():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    result = await crawler.scrape("   ")

    assert result.found is False
    # _result() stores error in data
    assert result.data.get("error") == "empty_identifier"


@pytest.mark.asyncio
async def test_namus_http_error():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    with patch.object(crawler, "post", AsyncMock(return_value=None)):
        result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_namus_rate_limited():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    with patch.object(crawler, "post", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.data.get("error") == "rate_limited"


@pytest.mark.asyncio
async def test_namus_non_200():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    with patch.object(crawler, "post", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.data.get("error") == "http_503"


@pytest.mark.asyncio
async def test_namus_parse_error():
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "post", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("Jane Doe")

    assert result.found is False
    assert result.data.get("error") == "parse_error"


@pytest.mark.asyncio
async def test_namus_single_name():
    """Single-word identifier → entire name used as last_name."""
    from modules.crawlers.people_namus import NamusCrawler

    crawler = NamusCrawler()
    payload = {"results": [], "total": 0}

    captured_payload = {}

    async def mock_post(url, json=None, headers=None, **kwargs):
        captured_payload.update(json or {})
        return _mock_resp(200, json_data=payload)

    with patch.object(crawler, "post", AsyncMock(side_effect=mock_post)):
        result = await crawler.scrape("Madonna")

    criteria = captured_payload.get("searchCriteria", {})
    assert criteria["firstName"] == ""
    assert criteria["lastName"] == "Madonna"


def test_namus_parse_case_sex_string():
    """_parse_case handles sex as a plain string (not dict)."""
    from modules.crawlers.people_namus import _parse_case

    case = dict(_NAMUS_CASE)
    case["subjectIdentification"] = dict(_NAMUS_CASE["subjectIdentification"])
    case["subjectIdentification"]["sex"] = "Male"
    result = _parse_case(case)
    assert result["sex"] == "Male"


def test_namus_parse_case_no_sightings():
    """_parse_case with empty sightings list → missing_city/state are ''."""
    from modules.crawlers.people_namus import _parse_case

    case = dict(_NAMUS_CASE)
    case["sightings"] = []
    result = _parse_case(case)
    assert result["missing_city"] == ""


def test_namus_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_namus")


# ===========================================================================
# PEOPLE_THATSTHEM — full coverage
# ===========================================================================


_THATSTHEM_HTML = """
<html><body>
<div class="record">
  <h2>John Smith</h2>
  <div class="address">123 Main St, Dallas TX 75201</div>
  <a href="tel:+12145550199">(214) 555-0199</a>
  <a href="mailto:john@example.com">john@example.com</a>
  <div class="age">Age 45</div>
</div>
</body></html>
"""


@pytest.mark.asyncio
async def test_thatsthem_name_found():
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text=_THATSTHEM_HTML)),
    ):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["mode"] == "name"
    assert any(p.get("name") for p in result.data["persons"])


@pytest.mark.asyncio
async def test_thatsthem_phone_lookup():
    """Phone number identifier → mode='phone'."""
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text=_THATSTHEM_HTML)),
    ):
        result = await crawler.scrape("+12145550199")

    assert result.data["mode"] == "phone"


@pytest.mark.asyncio
async def test_thatsthem_email_lookup():
    """Email identifier → mode='email'."""
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text=_THATSTHEM_HTML)),
    ):
        result = await crawler.scrape("john@example.com")

    assert result.data["mode"] == "email"


@pytest.mark.asyncio
async def test_thatsthem_http_error():
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    # Uses CrawlerResult(..., error=...) directly
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_thatsthem_rate_limited():
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_thatsthem_404():
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=404))):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    assert result.data["persons"] == []


@pytest.mark.asyncio
async def test_thatsthem_non_200():
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_thatsthem_no_persons_in_html():
    """200 but HTML has no record cards → found=False."""
    from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

    crawler = PeopleThatsThemCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, text="<html><body><p>No results found.</p></body></html>")),
    ):
        result = await crawler.scrape("Xyz Notreal")

    assert result.found is False


def test_thatsthem_build_url_phone():
    from modules.crawlers.people_thatsthem import _build_url

    url, mode = _build_url("+12145550199")
    assert mode == "phone"
    assert "/phone/" in url


def test_thatsthem_build_url_email():
    from modules.crawlers.people_thatsthem import _build_url

    url, mode = _build_url("test@example.com")
    assert mode == "email"
    assert "/email/" in url


def test_thatsthem_build_url_name_single():
    """Single-word name → slug has no trailing dash."""
    from modules.crawlers.people_thatsthem import _build_url

    url, mode = _build_url("Madonna")
    assert mode == "name"
    assert "/name/Madonna" in url
    assert not url.endswith("-")


def test_thatsthem_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_thatsthem")


def test_parse_persons_email_from_href():
    """Emails extracted from mailto: href when inner text is empty."""
    from modules.crawlers.people_thatsthem import _parse_persons

    html = """
    <div class="record">
      <h2>Alice</h2>
      <a href="mailto:alice@corp.com"></a>
    </div>
    """
    persons = _parse_persons(html)
    assert len(persons) == 1
    assert "alice@corp.com" in persons[0].get("emails", [])


# ===========================================================================
# PEOPLE_USMARSHALS — full coverage
# ===========================================================================


_USMS_API_RESPONSE = [
    {
        "name": "John Doe",
        "alias": "Johnny",
        "description": "Fugitive",
        "reward": "$50,000",
        "charges": "Bank robbery",
        "hair": "Black",
        "eyes": "Brown",
        "height": "5'11\"",
        "weight": "185 lbs",
        "sex": "Male",
        "race": "Hispanic",
        "nationality": "US",
        "lastKnownLocation": "Miami, FL",
        "caution": "Armed",
        "url": "https://usmarshals.gov/fugitive/johndoe",
    }
]

_USMS_HTML_PAGE = """
<html><body>
<h2>John Doe</h2>
<h2>Jane Smith</h2>
<h3>Robert Johnson</h3>
<p>Short</p>
</body></html>
"""


@pytest.mark.asyncio
async def test_usmarshals_api_found():
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=_USMS_API_RESPONSE)),
    ):
        result = await crawler.scrape("John Doe")

    assert result.found is True
    assert result.data["source"] == "api"
    assert len(result.data["fugitives"]) >= 1
    assert result.data["fugitives"][0]["name"] == "John Doe"


@pytest.mark.asyncio
async def test_usmarshals_api_data_key():
    """API returns dict with 'data' key → parsed correctly."""
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data={"data": _USMS_API_RESPONSE})),
    ):
        result = await crawler.scrape("John Doe")

    assert result.data["source"] == "api"


@pytest.mark.asyncio
async def test_usmarshals_api_results_key():
    """API returns dict with 'results' key → parsed correctly."""
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data={"results": _USMS_API_RESPONSE})),
    ):
        result = await crawler.scrape("John Doe")

    assert result.data["source"] == "api"


@pytest.mark.asyncio
async def test_usmarshals_api_fails_html_fallback_found():
    """API returns None → falls back to HTML; name matches in H2."""
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(
            side_effect=[
                None,  # API call fails
                _mock_resp(200, text=_USMS_HTML_PAGE),  # HTML fallback
            ]
        ),
    ):
        result = await crawler.scrape("John Doe")

    assert result.data["source"] == "html_fallback"
    assert result.found is True
    assert any("John" in f["name"] for f in result.data["fugitives"])


@pytest.mark.asyncio
async def test_usmarshals_api_parse_error_html_fallback():
    """API returns invalid JSON → falls back to HTML."""
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    bad_api_resp = MagicMock()
    bad_api_resp.status_code = 200
    bad_api_resp.json.side_effect = ValueError("bad json")

    with patch.object(
        crawler,
        "get",
        AsyncMock(
            side_effect=[
                bad_api_resp,
                _mock_resp(200, text=_USMS_HTML_PAGE),
            ]
        ),
    ):
        result = await crawler.scrape("John Doe")

    assert result.data["source"] == "html_fallback"


@pytest.mark.asyncio
async def test_usmarshals_html_fallback_also_fails():
    """Both API and HTML fail → http_error in data."""
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    with patch.object(
        crawler,
        "get",
        AsyncMock(side_effect=[None, None]),
    ):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_usmarshals_empty_identifier():
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    result = await crawler.scrape("  ")

    assert result.found is False
    assert result.data.get("error") == "empty_identifier"


@pytest.mark.asyncio
async def test_usmarshals_name_overlap_filter():
    """Fugitives with <0.3 name overlap are filtered out."""
    from modules.crawlers.people_usmarshals import USMarshalsCrawler

    crawler = USMarshalsCrawler()
    api_data = [
        {"name": "John Doe", "alias": "", "description": "", "reward": "",
         "charges": "", "hair": "", "eyes": "", "height": "", "weight": "",
         "sex": "", "race": "", "nationality": "", "lastKnownLocation": "",
         "caution": "", "url": ""},
        {"name": "Completely Different Person", "alias": "", "description": "",
         "reward": "", "charges": "", "hair": "", "eyes": "", "height": "",
         "weight": "", "sex": "", "race": "", "nationality": "",
         "lastKnownLocation": "", "caution": "", "url": ""},
    ]
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=api_data)),
    ):
        result = await crawler.scrape("John Doe")

    # "Completely Different Person" has 0/2 overlap with "John Doe" → filtered
    names = [f["name"] for f in result.data["fugitives"]]
    assert "Completely Different Person" not in names
    assert "John Doe" in names


def test_usmarshals_name_overlap_score():
    from modules.crawlers.people_usmarshals import _name_overlap_score

    assert _name_overlap_score("John Doe", "John Doe") == 1.0
    assert _name_overlap_score("John Doe", "John Smith") == 0.5
    assert _name_overlap_score("John Doe", "Alice Brown") == 0.0
    assert _name_overlap_score("", "John Doe") == 0.0


def test_usmarshals_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("people_usmarshals")


# ===========================================================================
# PHONE_CARRIER — uncovered branches
# ===========================================================================


@pytest.mark.asyncio
async def test_carrier_non_us_number():
    """International number uses different URL path."""
    from modules.crawlers.phone_carrier import CarrierLookupCrawler

    crawler = CarrierLookupCrawler()
    html = """
    <html><body>
    <table><tr><td>Carrier</td><td>Vodafone UK</td></tr>
    <tr><td>Type</td><td>Mobile Wireless</td></tr></table>
    </body></html>
    """
    captured_url = []

    async def mock_get(url, **kwargs):
        captured_url.append(url)
        return _mock_resp(200, text=html)

    with patch.object(crawler, "get", AsyncMock(side_effect=mock_get)):
        result = await crawler.scrape("+447911123456")

    assert "number=" in captured_url[0]
    assert result.found is True


@pytest.mark.asyncio
async def test_carrier_non_200_non_404():
    """503 → found=False with http_503."""
    from modules.crawlers.phone_carrier import CarrierLookupCrawler

    crawler = CarrierLookupCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_carrier_no_carrier_data():
    """HTML with no parseable carrier name → no_carrier_data error."""
    from modules.crawlers.phone_carrier import CarrierLookupCrawler

    crawler = CarrierLookupCrawler()
    html = "<html><body><p>No data available.</p></body></html>"
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "no_carrier_data"


@pytest.mark.asyncio
async def test_carrier_landline_detection():
    """Landline in HTML → line_type='landline', is_voip=False."""
    from modules.crawlers.phone_carrier import CarrierLookupCrawler

    crawler = CarrierLookupCrawler()
    html = """
    <html><body>
    <table>
      <tr><td>Carrier</td><td>AT&amp;T Landline</td></tr>
      <tr><td>Type</td><td>Wireline</td></tr>
    </table>
    </body></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["line_type"] == "landline"
    assert result.data["is_voip"] is False


def test_detect_line_type_all_variants():
    from modules.crawlers.phone_carrier import _detect_line_type
    from shared.constants import LineType

    assert _detect_line_type("VOIP service") == LineType.VOIP
    assert _detect_line_type("Mobile Wireless") == LineType.MOBILE
    assert _detect_line_type("Cellular network") == LineType.MOBILE
    assert _detect_line_type("wireline landline") == LineType.LANDLINE
    assert _detect_line_type("land line service") == LineType.LANDLINE
    assert _detect_line_type("prepaid plan") == LineType.PREPAID
    assert _detect_line_type("pre-paid option") == LineType.PREPAID
    assert _detect_line_type("toll free number") == LineType.TOLL_FREE
    assert _detect_line_type("unknown service") == LineType.UNKNOWN


def test_is_burner_carrier():
    from modules.crawlers.phone_carrier import _is_burner_carrier
    from shared.constants import BURNER_CARRIERS

    if BURNER_CARRIERS:
        first_burner = next(iter(BURNER_CARRIERS))
        assert _is_burner_carrier(f"Some {first_burner} Service") is True

    assert _is_burner_carrier("AT&T Legitimate Carrier Inc") is False


# ===========================================================================
# PHONE_FONEFINDER — uncovered branches
# ===========================================================================


@pytest.mark.asyncio
async def test_fonefinder_non_200_non_404():
    """503 → http_503 error."""
    from modules.crawlers.phone_fonefinder import FoneFinderCrawler

    crawler = FoneFinderCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("+15125551234")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_fonefinder_carrier_from_table():
    """Carrier found via standard table row."""
    from modules.crawlers.phone_fonefinder import FoneFinderCrawler

    crawler = FoneFinderCrawler()
    html = """
    <html><body>
    <table>
      <tr><td>Carrier</td><td>Sprint Nextel</td></tr>
      <tr><td>Location</td><td>Austin, TX</td></tr>
      <tr><td>Type</td><td>Mobile Wireless</td></tr>
    </table>
    </body></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("+15125551234")

    assert result.found is True
    assert result.data["carrier_name"] == "Sprint Nextel"
    assert result.data["city"] == "Austin"


@pytest.mark.asyncio
async def test_fonefinder_state_label_row():
    """Row with 'state' label extracts state abbreviation."""
    from modules.crawlers.phone_fonefinder import FoneFinderCrawler

    crawler = FoneFinderCrawler()
    html = """
    <html><body>
    <table>
      <tr><td>Carrier</td><td>T-Mobile USA</td></tr>
      <tr><td>State</td><td>TX</td></tr>
    </table>
    </body></html>
    """
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(200, text=html))):
        result = await crawler.scrape("+15125551234")

    assert result.found is True
    assert result.data["state"] == "TX"


def test_parse_city_state_no_us_state():
    """Text with non-US state abbreviation → returns empty strings."""
    from modules.crawlers.phone_fonefinder import _parse_city_state

    city, state = _parse_city_state("London, UK")
    assert city == "" and state == ""


def test_parse_city_state_with_comma():
    from modules.crawlers.phone_fonefinder import _parse_city_state

    city, state = _parse_city_state("Austin, TX")
    assert city == "Austin"
    assert state == "TX"


# ===========================================================================
# PHONE_NUMLOOKUP — full coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_numlookup_found_valid():
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    data = {
        "valid": True,
        "number_type": "mobile",
        "carrier": "Verizon",
        "country_code": "US",
        "country_name": "United States",
        "formatted": "+1 202-555-1234",
    }
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=data))
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["carrier"] == "Verizon"
    assert result.data["country_code"] == "US"
    assert result.data["valid"] is True


@pytest.mark.asyncio
async def test_numlookup_invalid_number():
    """valid=False → found=False."""
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    data = {"valid": False, "number_type": None, "carrier": None, "country_code": None}
    with patch.object(
        crawler, "get", AsyncMock(return_value=_mock_resp(200, json_data=data))
    ):
        result = await crawler.scrape("+00000000")

    assert result.found is False


@pytest.mark.asyncio
async def test_numlookup_http_error():
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=None)):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    # Uses CrawlerResult(..., error=...) directly
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_numlookup_unauthorized():
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=401))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "unauthorized_no_api_key"


@pytest.mark.asyncio
async def test_numlookup_rate_limited():
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=429))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_numlookup_non_200():
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_numlookup_invalid_json():
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "invalid_json"


@pytest.mark.asyncio
async def test_numlookup_with_api_key():
    """With api_key, URL includes the key parameter."""
    from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

    crawler = PhoneNumLookupCrawler()
    data = {"valid": True, "carrier": "Sprint", "country_code": "US",
            "country_name": "United States", "formatted": "+1 555 0001",
            "number_type": "mobile"}

    captured_url = []

    async def mock_get(url, **kwargs):
        captured_url.append(url)
        return _mock_resp(200, json_data=data)

    # Patch at module level to avoid pydantic field issues
    with (
        patch("modules.crawlers.phone_numlookup.settings") as mock_settings,
        patch.object(crawler, "get", AsyncMock(side_effect=mock_get)),
    ):
        mock_settings.numlookup_api_key = "myapikey123"
        result = await crawler.scrape("+15551234567")

    assert "apikey=myapikey123" in captured_url[0]
    assert result.found is True


def test_numlookup_registered():
    from modules.crawlers.registry import is_registered

    assert is_registered("phone_numlookup")


# ===========================================================================
# PHONE_TRUECALLER — uncovered branches
# ===========================================================================


@pytest.mark.asyncio
async def test_truecaller_non_200_non_404():
    """503 → http_503 error."""
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_resp(status=503))):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "http_503"


@pytest.mark.asyncio
async def test_truecaller_json_parse_error():
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("+12025551234")

    assert result.found is False
    assert result.error == "json_parse_error"


@pytest.mark.asyncio
async def test_truecaller_voip_line_type():
    """VOIP type code in phones → line_type='voip'."""
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    payload = {
        "data": [
            {
                "name": "VoIP User",
                "score": 0.3,
                "tags": [],
                "phones": [{"carrier": "Twilio", "type": "VOIP"}],
            }
        ]
    }
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=payload)),
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["line_type"] == "voip"


@pytest.mark.asyncio
async def test_truecaller_numeric_type_code():
    """Numeric type code (0 = mobile) → line_type='mobile'."""
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    payload = {
        "data": [
            {
                "name": "Mobile User",
                "score": 0.9,
                "tags": [{"tag": "spam"}],
                "phones": [{"carrier": "Verizon", "type": 0}],
            }
        ]
    }
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=payload)),
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["line_type"] == "mobile"


@pytest.mark.asyncio
async def test_truecaller_intl_number_uses_us_fallback():
    """INTL country code falls back to 'US' for Truecaller query."""
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    payload = {
        "data": [
            {
                "name": "Intl User",
                "score": 0.5,
                "tags": [],
                "phones": [{"carrier": "Generic", "type": "MOBILE"}],
            }
        ]
    }
    captured_url = []

    async def mock_get(url, headers=None, **kwargs):
        captured_url.append(url)
        return _mock_resp(200, json_data=payload)

    with patch.object(crawler, "get", AsyncMock(side_effect=mock_get)):
        result = await crawler.scrape("+447911123456")

    # INTL number → country_code fallback to "US" in query
    assert len(captured_url) == 1
    assert "countryCode=US" in captured_url[0]


@pytest.mark.asyncio
async def test_truecaller_tag_as_string():
    """Tags that are plain strings (not dicts) are handled."""
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    payload = {
        "data": [
            {
                "name": "Tagged User",
                "score": 0.7,
                "tags": ["spam", "telemarketer"],
                "phones": [{"carrier": "ATT", "type": "MOBILE"}],
            }
        ]
    }
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=payload)),
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert "spam" in result.data["tags"]
    assert "telemarketer" in result.data["tags"]


@pytest.mark.asyncio
async def test_truecaller_no_phones_in_record():
    """Record with empty phones list → carrier='', line_type=UNKNOWN."""
    from modules.crawlers.phone_truecaller import TruecallerCrawler

    crawler = TruecallerCrawler()
    payload = {
        "data": [
            {
                "name": "No Phone Data",
                "score": 0.1,
                "tags": [],
                "phones": [],
            }
        ]
    }
    with patch.object(
        crawler,
        "get",
        AsyncMock(return_value=_mock_resp(200, json_data=payload)),
    ):
        result = await crawler.scrape("+12025551234")

    assert result.found is True
    assert result.data["carrier"] == ""


def test_truecaller_tc_line_type_mapping():
    """Verify all _TC_LINE_TYPE entries resolve correctly."""
    from modules.crawlers.phone_truecaller import _TC_LINE_TYPE
    from shared.constants import LineType

    assert _TC_LINE_TYPE["MOBILE"] == LineType.MOBILE.value
    assert _TC_LINE_TYPE["FIXED_LINE"] == LineType.LANDLINE.value
    assert _TC_LINE_TYPE["VOIP"] == LineType.VOIP.value
    assert _TC_LINE_TYPE["TOLL_FREE"] == LineType.TOLL_FREE.value
    assert _TC_LINE_TYPE[1] == LineType.LANDLINE.value
    assert _TC_LINE_TYPE[3] == LineType.VOIP.value
