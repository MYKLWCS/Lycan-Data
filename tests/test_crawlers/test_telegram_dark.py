"""
Tests for the Telegram dark channel scanner:
  - TelegramDarkCrawler (telegram_dark) — 10 tests
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.telegram_dark  # noqa: F401
from modules.crawlers.registry import is_registered
from modules.crawlers.telegram_dark import (
    DARK_CHANNELS,
    TelegramDarkCrawler,
    _filter_mentions,
    _parse_channel_messages,
)
from shared.tor import TorInstance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status_code: int = 200, text: str = "") -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    return mock


_CHANNEL_HTML = """
<html><body>
<div class="tgme_widget_message">
  <div class="tgme_widget_message_text">
    Massive breach at example.com — 500k credentials leaked online.
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/darkwebinformer/1001">
    <time datetime="2024-03-15T10:00:00+00:00">2024-03-15</time>
  </a>
</div>
<div class="tgme_widget_message">
  <div class="tgme_widget_message_text">
    Unrelated news about something else entirely.
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/darkwebinformer/1002">
    <time datetime="2024-03-15T11:00:00+00:00">2024-03-15</time>
  </a>
</div>
</body></html>
"""

_EMPTY_CHANNEL_HTML = "<html><body><div class='tgme_no_messages'>No posts yet.</div></body></html>"


# ---------------------------------------------------------------------------
# TelegramDarkCrawler — 10 tests
# ---------------------------------------------------------------------------


def test_telegram_dark_registered():
    """telegram_dark must appear in the crawler registry."""
    assert is_registered("telegram_dark")


def test_dark_channels_list_not_empty():
    """DARK_CHANNELS must be a non-empty list of channel names."""
    assert isinstance(DARK_CHANNELS, list)
    assert len(DARK_CHANNELS) >= 4
    assert all(isinstance(ch, str) and ch for ch in DARK_CHANNELS)


def test_parse_channel_messages_extracts_messages():
    """_parse_channel_messages pulls text, URL, and datetime from HTML."""
    messages = _parse_channel_messages(_CHANNEL_HTML)
    assert len(messages) == 2
    assert "example.com" in messages[0]["message_text"]
    assert messages[0]["message_url"] == "https://t.me/darkwebinformer/1001"
    assert "2024-03-15" in messages[0]["date"]


def test_parse_channel_messages_empty_html():
    """Empty channel page returns empty message list without raising."""
    messages = _parse_channel_messages(_EMPTY_CHANNEL_HTML)
    assert messages == []


def test_filter_mentions_case_insensitive():
    """_filter_mentions matches query case-insensitively."""
    messages = [
        {
            "message_text": "Breach at EXAMPLE.COM today",
            "message_url": "https://t.me/ch/1",
            "date": "2024-01-01",
        },
        {
            "message_text": "Unrelated content",
            "message_url": "https://t.me/ch/2",
            "date": "2024-01-01",
        },
    ]
    hits = _filter_mentions(messages, "example.com", "testchannel")
    assert len(hits) == 1
    assert hits[0]["channel"] == "testchannel"
    assert hits[0]["message_url"] == "https://t.me/ch/1"


def test_filter_mentions_no_match():
    """_filter_mentions returns empty list when query does not appear."""
    messages = [
        {
            "message_text": "Nothing relevant here at all",
            "message_url": "https://t.me/ch/3",
            "date": "2024-01-01",
        },
    ]
    hits = _filter_mentions(messages, "example.com", "testchannel")
    assert hits == []


@pytest.mark.asyncio
async def test_telegram_dark_scrape_finds_mentions():
    """
    When one channel contains the query, the result has found=True and
    the mention data is populated with channel, message_text, and message_url.
    """
    crawler = TelegramDarkCrawler()

    # Return matching HTML for first channel, empty for the rest
    def _side_effect(url, **kwargs):
        if DARK_CHANNELS[0] in url:
            return _mock_resp(200, _CHANNEL_HTML)
        return _mock_resp(200, _EMPTY_CHANNEL_HTML)

    with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
        with patch("modules.crawlers.telegram_dark.asyncio.sleep", new=AsyncMock()):
            result = await crawler.scrape("example.com")

    assert result.found is True
    assert result.platform == "telegram_dark"
    assert result.data["mention_count"] >= 1
    mention = result.data["mentions"][0]
    assert mention["channel"] == DARK_CHANNELS[0]
    assert "example.com" in mention["message_text"].lower()
    assert mention["message_url"].startswith("https://t.me/")


@pytest.mark.asyncio
async def test_telegram_dark_scrape_no_mentions():
    """When no channel contains the query, returns found=False with empty list."""
    crawler = TelegramDarkCrawler()

    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_resp(200, _EMPTY_CHANNEL_HTML))
    ):
        with patch("modules.crawlers.telegram_dark.asyncio.sleep", new=AsyncMock()):
            result = await crawler.scrape("xyznonexistentquery999")

    assert result.found is False
    assert result.data["mention_count"] == 0
    assert result.data["mentions"] == []


@pytest.mark.asyncio
async def test_telegram_dark_http_failure_skips_channel():
    """
    A None response for a channel is skipped; other channels are still checked.
    The overall result is based on whichever channels respond successfully.
    """
    crawler = TelegramDarkCrawler()
    call_count = 0

    def _side_effect(url, **kwargs):
        nonlocal call_count
        call_count += 1
        # Fail first two, succeed on third with matching content
        if call_count <= 2:
            return None
        if call_count == 3:
            return _mock_resp(200, _CHANNEL_HTML)
        return _mock_resp(200, _EMPTY_CHANNEL_HTML)

    with patch.object(crawler, "get", new=AsyncMock(side_effect=_side_effect)):
        with patch("modules.crawlers.telegram_dark.asyncio.sleep", new=AsyncMock()):
            result = await crawler.scrape("example.com")

    # At least attempted multiple channels
    assert call_count >= 3
    # Found because third channel matched
    assert result.found is True


def test_telegram_dark_tor_and_reliability():
    """telegram_dark uses TOR2 with source_reliability 0.45."""
    crawler = TelegramDarkCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2
    assert crawler.source_reliability == pytest.approx(0.45)
