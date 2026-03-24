from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.linkedin import LinkedInCrawler
from modules.crawlers.reddit import RedditCrawler
from modules.crawlers.registry import is_registered
from modules.crawlers.telegram import TelegramCrawler
from modules.crawlers.tiktok import TikTokCrawler
from modules.crawlers.whatsapp import WhatsAppCrawler
from modules.crawlers.youtube import YouTubeCrawler


# --- Registry checks ---
def test_all_platforms_registered():
    for platform in ["tiktok", "linkedin", "reddit", "youtube", "telegram", "whatsapp"]:
        assert is_registered(platform), f"{platform} not registered"


# --- Reddit (real JSON API mock) ---
@pytest.mark.asyncio
async def test_reddit_profile_parsed():
    crawler = RedditCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(
        return_value={
            "data": {
                "name": "testuser",
                "id": "abc123",
                "link_karma": 500,
                "comment_karma": 1200,
                "created_utc": 1609459200.0,
                "verified": False,
                "is_gold": False,
                "has_verified_email": True,
            }
        }
    )

    posts_resp = MagicMock()
    posts_resp.status_code = 200
    posts_resp.json = MagicMock(return_value={"data": {"children": []}})

    with patch.object(crawler, "get", AsyncMock(side_effect=[mock_resp, posts_resp])):
        result = await crawler.scrape("testuser")

    assert result.found is True
    assert result.data["display_name"] == "testuser"
    assert result.data["link_karma"] == 500


@pytest.mark.asyncio
async def test_reddit_not_found():
    crawler = RedditCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("xyzdefnotreal999")

    assert result.found is False


# --- TikTok ---
@pytest.mark.asyncio
async def test_tiktok_not_found():
    crawler = TikTokCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Couldn't find this account"

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("xyznotreal999")

    assert result.found is False


@pytest.mark.asyncio
async def test_tiktok_parses_json_data():
    import json

    crawler = TikTokCrawler()
    mock_data = {
        "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
                "userInfo": {
                    "user": {
                        "nickname": "TikTok Star",
                        "signature": "Content creator",
                        "verified": True,
                        "id": "12345",
                    },
                    "stats": {
                        "followerCount": 500000,
                        "followingCount": 100,
                        "videoCount": 200,
                        "heartCount": 1000000,
                    },
                }
            }
        }
    }
    html = f'<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{json.dumps(mock_data)}</script></html>'
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("tikTokStar")

    assert result.found is True
    assert result.data["display_name"] == "TikTok Star"
    assert result.data["follower_count"] == 500000
    assert result.data["is_verified"] is True


# --- WhatsApp ---
@pytest.mark.asyncio
async def test_whatsapp_registered():
    crawler = WhatsAppCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html>Send message to continue to WhatsApp</html>"
    mock_resp.url = "https://wa.me/15551234567"

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("+15551234567")

    assert result.found is True
    assert result.data["whatsapp_registered"] is True


@pytest.mark.asyncio
async def test_whatsapp_not_registered():
    crawler = WhatsAppCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html>The phone number shared via link may not be on WhatsApp</html>"
    mock_resp.url = "https://wa.me/15559999999"

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("+15559999999")

    assert result.found is False
    assert result.data["whatsapp_registered"] is False


# --- Telegram (no Telethon configured) ---
@pytest.mark.asyncio
async def test_telegram_phone_no_telethon():
    crawler = TelegramCrawler()
    import os

    with patch.dict(os.environ, {}, clear=False):
        # Ensure env vars not set
        for key in ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION"]:
            os.environ.pop(key, None)
        result = await crawler.scrape("+15551234567")
    assert result.data["telegram_registered"] is None
    assert "telethon_not_configured" in result.error


@pytest.mark.asyncio
async def test_telegram_username_found():
    crawler = TelegramCrawler()
    html = """
    <html><body>
    <div class="tgme_page_title">Test Channel</div>
    <div class="tgme_page_description">A test channel bio</div>
    <div class="tgme_page_extra">1,234 subscribers</div>
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("testchannel")

    assert result.found is True
    assert result.data["display_name"] == "Test Channel"
    assert result.data["follower_count"] == 1234


# --- YouTube ---
@pytest.mark.asyncio
async def test_youtube_channel_found():
    crawler = YouTubeCrawler()
    html = """
    <html><head>
    <title>Test Channel - YouTube</title>
    <meta name="description" content="Welcome to Test Channel">
    </head></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_resp.url = "https://www.youtube.com/@testchannel"

    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("testchannel")

    assert result.found is True
    assert result.data["display_name"] == "Test Channel"
