"""
test_base_wave5.py — Coverage gap tests for modules/crawlers/base.py.

Targets:
  - Lines 88-89: rotate_circuit() calls tor_manager.new_circuit() and logs info.
    This is the async rotate_circuit method on BaseCrawler.
  - Lines 87-99: get_proxy_async() branches.
  - Line 106: get_proxy() proxy_override branch.
  - Lines 128-132: _handle_ban_response() branches.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

# ---------------------------------------------------------------------------
# Concrete subclass for testing (BaseCrawler is abstract)
# ---------------------------------------------------------------------------


class _DummyCrawler(BaseCrawler):
    platform = "dummy"
    source_reliability = 0.5
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        return self._result(identifier, found=False)


# ---------------------------------------------------------------------------
# Lines 88-89: rotate_circuit()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_circuit_calls_tor_manager():
    """
    Line 88: await tor_manager.new_circuit(self.tor_instance)
    Line 89: logger.info(...)
    Both are exercised when rotate_circuit() is called.
    """
    crawler = _DummyCrawler()

    with patch("modules.crawlers.base.tor_manager") as mock_tor_mgr:
        mock_tor_mgr.new_circuit = AsyncMock()

        await crawler.rotate_circuit()

        mock_tor_mgr.new_circuit.assert_awaited_once_with(TorInstance.TOR2)


@pytest.mark.asyncio
async def test_rotate_circuit_logs_platform_name():
    """
    Line 89: logger.info logs the platform name after rotating.
    """
    crawler = _DummyCrawler()

    with patch("modules.crawlers.base.tor_manager") as mock_tor_mgr:
        mock_tor_mgr.new_circuit = AsyncMock()
        with patch("modules.crawlers.base.logger") as mock_log:
            await crawler.rotate_circuit()

            mock_log.info.assert_called_once()
            call_args = mock_log.info.call_args
            # The platform name "dummy" appears in the log message
            assert "dummy" in str(call_args)


@pytest.mark.asyncio
async def test_rotate_circuit_uses_crawler_tor_instance():
    """
    Line 88: The crawler's tor_instance attribute is passed to new_circuit.
    """
    crawler = _DummyCrawler()
    crawler.tor_instance = TorInstance.TOR1

    with patch("modules.crawlers.base.tor_manager") as mock_tor_mgr:
        mock_tor_mgr.new_circuit = AsyncMock()
        await crawler.rotate_circuit()

        mock_tor_mgr.new_circuit.assert_awaited_once_with(TorInstance.TOR1)


# ---------------------------------------------------------------------------
# Lines 87-99: get_proxy_async() branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_proxy_async_opts_out_when_no_tor_and_tier_is_tor():
    """
    Line 90-91: requires_tor=False and proxy_tier="tor" → return None immediately.
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = False
    crawler.proxy_tier = "tor"

    result = await crawler.get_proxy_async()
    assert result is None


@pytest.mark.asyncio
async def test_get_proxy_async_downgrades_tor_tier_when_tor_disabled():
    """
    Lines 94-96: proxy_tier="tor" but tor_enabled=False → tier becomes "datacenter".
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = True
    crawler.proxy_tier = "tor"

    mock_pool = MagicMock()
    mock_pool.next_with_fallback = AsyncMock(return_value=("socks5://127.0.0.1:9050", "datacenter"))

    mock_settings = MagicMock()
    mock_settings.tor_enabled = False

    import unittest.mock as _mock

    import shared.proxy_pool as _pp_mod

    with _mock.patch.object(_pp_mod, "proxy_pool", mock_pool):
        with patch("modules.crawlers.base.settings", mock_settings):
            result = await crawler.get_proxy_async()

    mock_pool.next_with_fallback.assert_awaited_once_with("datacenter")
    assert result == "socks5://127.0.0.1:9050"


@pytest.mark.asyncio
async def test_get_proxy_async_uses_preferred_tier_when_tor_enabled():
    """
    Lines 97-99: proxy_tier="residential" and tor is enabled → uses "residential".
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = True
    crawler.proxy_tier = "residential"

    mock_pool = MagicMock()
    mock_pool.next_with_fallback = AsyncMock(return_value=("http://residential.proxy:8080", "residential"))

    mock_settings = MagicMock()
    mock_settings.tor_enabled = True

    with patch("shared.proxy_pool.proxy_pool", mock_pool, create=True):
        with patch("modules.crawlers.base.settings", mock_settings):
            result = await crawler.get_proxy_async()

    mock_pool.next_with_fallback.assert_awaited_once_with("residential")
    assert result == "http://residential.proxy:8080"


@pytest.mark.asyncio
async def test_get_proxy_async_returns_none_proxy_from_pool():
    """
    Lines 97-99: pool returns (None, tier) → method returns None.
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = True
    crawler.proxy_tier = "datacenter"

    mock_pool = MagicMock()
    mock_pool.next_with_fallback = AsyncMock(return_value=(None, "datacenter"))

    mock_settings = MagicMock()
    mock_settings.tor_enabled = True

    with patch("shared.proxy_pool.proxy_pool", mock_pool, create=True):
        with patch("modules.crawlers.base.settings", mock_settings):
            result = await crawler.get_proxy_async()

    assert result is None


# ---------------------------------------------------------------------------
# Line 106: get_proxy() proxy_override branch
# ---------------------------------------------------------------------------


def test_get_proxy_returns_proxy_override_when_set():
    """
    Line 105-106: requires_tor=True and settings.proxy_override is set → return it.
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = True

    mock_settings = MagicMock()
    mock_settings.proxy_override = "socks5://custom.proxy:9999"

    with patch("modules.crawlers.base.settings", mock_settings):
        result = crawler.get_proxy()

    assert result == "socks5://custom.proxy:9999"


def test_get_proxy_returns_none_when_requires_tor_false():
    """
    Line 103-104: requires_tor=False → return None immediately.
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = False

    result = crawler.get_proxy()
    assert result is None


def test_get_proxy_falls_back_to_tor_manager():
    """
    Line 107: no proxy_override → call tor_manager.get_proxy().
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = True

    mock_settings = MagicMock()
    mock_settings.proxy_override = None  # falsy → go to tor_manager

    with (
        patch("modules.crawlers.base.settings", mock_settings),
        patch("modules.crawlers.base.tor_manager") as mock_tor_mgr,
    ):
        mock_tor_mgr.get_proxy = MagicMock(return_value="socks5://tor.exit:9050")
        result = crawler.get_proxy()

    assert result == "socks5://tor.exit:9050"
    mock_tor_mgr.get_proxy.assert_called_once_with(TorInstance.TOR2)


def test_get_proxy_returns_none_when_tor_manager_returns_falsy():
    """
    Line 107: tor_manager.get_proxy() returns empty string → or None → return None.
    """
    crawler = _DummyCrawler()
    crawler.requires_tor = True

    mock_settings = MagicMock()
    mock_settings.proxy_override = None

    with (
        patch("modules.crawlers.base.settings", mock_settings),
        patch("modules.crawlers.base.tor_manager") as mock_tor_mgr,
    ):
        mock_tor_mgr.get_proxy = MagicMock(return_value="")
        result = crawler.get_proxy()

    assert result is None


# ---------------------------------------------------------------------------
# Lines 128-132: _handle_ban_response() branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_ban_response_403_with_proxy():
    """
    Line 128-132: proxy is set, status 403 → mark_banned + rotate_circuit called.
    """
    crawler = _DummyCrawler()
    proxy = "socks5://10.0.0.1:9050"

    mock_pool = MagicMock()
    mock_pool.mark_banned = AsyncMock()

    with (
        patch("shared.proxy_pool.proxy_pool", mock_pool, create=True),
        patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
    ):
        await crawler._handle_ban_response(proxy, 403)

    mock_pool.mark_banned.assert_awaited_once_with(proxy, duration_minutes=20)
    mock_rotate.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_ban_response_429_with_proxy():
    """Status 429 also triggers ban handling."""
    crawler = _DummyCrawler()
    proxy = "http://resi.proxy:8080"

    mock_pool = MagicMock()
    mock_pool.mark_banned = AsyncMock()

    with (
        patch("shared.proxy_pool.proxy_pool", mock_pool, create=True),
        patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
    ):
        await crawler._handle_ban_response(proxy, 429)

    mock_pool.mark_banned.assert_awaited_once()
    mock_rotate.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_ban_response_503_with_proxy():
    """Status 503 also triggers ban handling."""
    crawler = _DummyCrawler()
    proxy = "socks5://tor:9050"

    mock_pool = MagicMock()
    mock_pool.mark_banned = AsyncMock()

    with (
        patch("shared.proxy_pool.proxy_pool", mock_pool, create=True),
        patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
    ):
        await crawler._handle_ban_response(proxy, 503)

    mock_pool.mark_banned.assert_awaited_once()
    mock_rotate.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_ban_response_none_proxy_does_nothing():
    """
    Line 128: proxy is None → the if-branch is skipped entirely.
    """
    crawler = _DummyCrawler()

    mock_pool = MagicMock()
    mock_pool.mark_banned = AsyncMock()

    with (
        patch("shared.proxy_pool.proxy_pool", mock_pool, create=True),
        patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
    ):
        await crawler._handle_ban_response(None, 403)

    mock_pool.mark_banned.assert_not_awaited()
    mock_rotate.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_ban_response_non_ban_status_does_nothing():
    """
    Line 128: status 200 is not in (403, 429, 503) → if-branch skipped.
    """
    crawler = _DummyCrawler()
    proxy = "socks5://10.0.0.1:9050"

    mock_pool = MagicMock()
    mock_pool.mark_banned = AsyncMock()

    with (
        patch("shared.proxy_pool.proxy_pool", mock_pool, create=True),
        patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
    ):
        await crawler._handle_ban_response(proxy, 200)

    mock_pool.mark_banned.assert_not_awaited()
    mock_rotate.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_ban_response_404_does_nothing():
    """Status 404 is not a ban signal."""
    crawler = _DummyCrawler()

    mock_pool = MagicMock()
    mock_pool.mark_banned = AsyncMock()

    with (
        patch("shared.proxy_pool.proxy_pool", mock_pool, create=True),
        patch.object(crawler, "rotate_circuit", new=AsyncMock()) as mock_rotate,
    ):
        await crawler._handle_ban_response("socks5://x:9050", 404)

    mock_pool.mark_banned.assert_not_awaited()
    mock_rotate.assert_not_awaited()
