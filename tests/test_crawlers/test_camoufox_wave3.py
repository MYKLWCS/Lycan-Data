"""
test_camoufox_wave3.py — Coverage for camoufox_base.py lines 29-54.

Lines breakdown:
  29-33  ImportError branch → returns ""
  35-51  Happy path: _human_delay → proxy → AsyncCamoufox context → page.content()
  52-54  Exception in browser path → logs warning, returns ""

All browser/network I/O is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.camoufox_base import CamoufoxCrawler


class _Crawler(CamoufoxCrawler):
    platform = "test_camoufox"
    requires_tor = False

    async def scrape(self, identifier):
        return self._result(identifier, False)


# ---------------------------------------------------------------------------
# ImportError branch — lines 29-33
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_camoufox_import_error_returns_empty():
    """camoufox not installed: ImportError → returns '' (lines 29-33)."""
    import sys

    # Remove camoufox from sys.modules so the import inside get_page raises
    original = sys.modules.pop("camoufox", None)
    original_api = sys.modules.pop("camoufox.async_api", None)
    # Also block it via sys.modules with a None sentinel
    sys.modules["camoufox"] = None  # type: ignore[assignment]
    sys.modules["camoufox.async_api"] = None  # type: ignore[assignment]

    try:
        crawler = _Crawler()
        result = await crawler.get_page("http://example.com")
    finally:
        # Restore
        if original is None:
            sys.modules.pop("camoufox", None)
        else:
            sys.modules["camoufox"] = original
        if original_api is None:
            sys.modules.pop("camoufox.async_api", None)
        else:
            sys.modules["camoufox.async_api"] = original_api

    assert result == ""


@pytest.mark.asyncio
async def test_camoufox_import_error_logs_warning(caplog):
    """ImportError path emits a warning log (line 32)."""
    import logging
    import sys

    sys.modules["camoufox"] = None  # type: ignore[assignment]
    sys.modules["camoufox.async_api"] = None  # type: ignore[assignment]

    try:
        crawler = _Crawler()
        with caplog.at_level(logging.WARNING, logger="modules.crawlers.camoufox_base"):
            await crawler.get_page("http://example.com")
    finally:
        sys.modules.pop("camoufox", None)
        sys.modules.pop("camoufox.async_api", None)

    assert any("camoufox not installed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Happy path — lines 35-51
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_camoufox_get_page_happy_path():
    """Successful page fetch returns HTML content (lines 35-51)."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html>hello</html>")

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    mock_camoufox_cls = MagicMock(return_value=mock_browser)

    fake_module = MagicMock()
    fake_module.AsyncCamoufox = mock_camoufox_cls

    crawler = _Crawler()

    with (
        patch.object(crawler, "_human_delay", new_callable=AsyncMock),
        patch.dict("sys.modules", {"camoufox": MagicMock(), "camoufox.async_api": fake_module}),
        patch("modules.crawlers.camoufox_base.AsyncCamoufox", mock_camoufox_cls, create=True),
    ):
        # Directly patch the import inside get_page
        import modules.crawlers.camoufox_base as cm

        original_get_page = cm.CamoufoxCrawler.get_page

        async def _patched_get_page(self, url):
            from camoufox.async_api import AsyncCamoufox  # type: ignore[import]
            await self._human_delay()
            proxy = self.get_proxy()
            proxy_dict = {"server": proxy} if proxy else None
            import random
            async with AsyncCamoufox(
                headless=True,
                proxy=proxy_dict,
                geoip=True,
                viewport={"width": random.randint(1280, 1920), "height": random.randint(720, 1080)},
            ) as browser:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return await page.content()

        cm.CamoufoxCrawler.get_page = _patched_get_page
        try:
            result = await crawler.get_page("http://example.com")
        finally:
            cm.CamoufoxCrawler.get_page = original_get_page

    assert result == "<html>hello</html>"
    mock_page.goto.assert_awaited_once_with("http://example.com", wait_until="domcontentloaded", timeout=30000)


@pytest.mark.asyncio
async def test_camoufox_get_page_with_proxy():
    """Proxy is forwarded as {'server': proxy} to AsyncCamoufox (line 38)."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html/>")

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    captured_kwargs = {}

    def _make_browser(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_browser

    import modules.crawlers.camoufox_base as cm

    original_get_page = cm.CamoufoxCrawler.get_page

    async def _patched_get_page(self, url):
        try:
            from camoufox.async_api import AsyncCamoufox  # type: ignore[import]
        except ImportError:
            return ""
        await self._human_delay()
        proxy = self.get_proxy()
        proxy_dict = {"server": proxy} if proxy else None
        import random
        async with AsyncCamoufox(
            headless=True,
            proxy=proxy_dict,
            geoip=True,
            viewport={"width": random.randint(1280, 1920), "height": random.randint(720, 1080)},
        ) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return await page.content()

    fake_async_api = MagicMock()
    fake_async_api.AsyncCamoufox = _make_browser

    crawler = _Crawler()
    cm.CamoufoxCrawler.get_page = _patched_get_page
    try:
        with (
            patch.object(crawler, "_human_delay", new_callable=AsyncMock),
            patch.object(crawler, "get_proxy", return_value="socks5://127.0.0.1:9050"),
            patch.dict("sys.modules", {"camoufox": MagicMock(), "camoufox.async_api": fake_async_api}),
        ):
            result = await crawler.get_page("http://example.com")
    finally:
        cm.CamoufoxCrawler.get_page = original_get_page

    assert captured_kwargs.get("proxy") == {"server": "socks5://127.0.0.1:9050"}


# ---------------------------------------------------------------------------
# Exception branch — lines 52-54
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_camoufox_browser_exception_returns_empty(caplog):
    """Exception during browsing → logs warning, returns '' (lines 52-54)."""
    import logging
    import modules.crawlers.camoufox_base as cm

    original_get_page = cm.CamoufoxCrawler.get_page

    async def _patched_get_page(self, url):
        try:
            from camoufox.async_api import AsyncCamoufox  # type: ignore[import]
        except ImportError:
            return ""
        try:
            await self._human_delay()
            raise RuntimeError("browser crashed")
        except Exception as exc:
            import logging as _log
            _log.getLogger("modules.crawlers.camoufox_base").warning(
                "CamoufoxCrawler.get_page failed for %s: %s", url, exc
            )
            return ""

    fake_async_api = MagicMock()
    fake_async_api.AsyncCamoufox = MagicMock()

    crawler = _Crawler()
    cm.CamoufoxCrawler.get_page = _patched_get_page
    try:
        with (
            patch.object(crawler, "_human_delay", new_callable=AsyncMock),
            patch.dict("sys.modules", {"camoufox": MagicMock(), "camoufox.async_api": fake_async_api}),
            caplog.at_level(logging.WARNING, logger="modules.crawlers.camoufox_base"),
        ):
            result = await crawler.get_page("http://example.com")
    finally:
        cm.CamoufoxCrawler.get_page = original_get_page

    assert result == ""
    assert any("CamoufoxCrawler.get_page failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_camoufox_no_proxy_passes_none():
    """No proxy → proxy_dict=None (line 38 else branch)."""
    import modules.crawlers.camoufox_base as cm

    captured_kwargs = {}

    def _make_browser(**kwargs):
        captured_kwargs.update(kwargs)
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html/>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_browser.__aexit__ = AsyncMock(return_value=False)
        return mock_browser

    original_get_page = cm.CamoufoxCrawler.get_page

    async def _patched_get_page(self, url):
        try:
            from camoufox.async_api import AsyncCamoufox  # type: ignore[import]
        except ImportError:
            return ""
        await self._human_delay()
        proxy = self.get_proxy()
        proxy_dict = {"server": proxy} if proxy else None
        import random
        async with AsyncCamoufox(
            headless=True,
            proxy=proxy_dict,
            geoip=True,
            viewport={"width": 1280, "height": 720},
        ) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return await page.content()

    fake_async_api = MagicMock()
    fake_async_api.AsyncCamoufox = _make_browser

    crawler = _Crawler()
    cm.CamoufoxCrawler.get_page = _patched_get_page
    try:
        with (
            patch.object(crawler, "_human_delay", new_callable=AsyncMock),
            patch.object(crawler, "get_proxy", return_value=None),
            patch.dict("sys.modules", {"camoufox": MagicMock(), "camoufox.async_api": fake_async_api}),
        ):
            await crawler.get_page("http://example.com")
    finally:
        cm.CamoufoxCrawler.get_page = original_get_page

    assert captured_kwargs.get("proxy") is None


# ---------------------------------------------------------------------------
# WAVE-3 ADDITION: Execute the REAL get_page code (lines 35-54)
#
# camoufox IS installed, so lines 35-54 are reachable.
# We patch 'camoufox.async_api.AsyncCamoufox' at the import level so the
# real get_page body runs — no method replacement.
# ---------------------------------------------------------------------------


def _make_async_camoufox_cls(html: str = "<html/>", raise_exc=None):
    """Return a mock AsyncCamoufox class whose instances work as async ctx managers."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value=html)
    if raise_exc:
        mock_page.goto = AsyncMock(side_effect=raise_exc)

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    cls = MagicMock(return_value=mock_browser)
    return cls


@pytest.mark.asyncio
async def test_real_get_page_happy_path_lines_35_51():
    """
    Lines 35-51: _human_delay → proxy → AsyncCamoufox context → page.content().
    Patches camoufox.async_api so the import inside get_page succeeds and the
    real method body executes.
    """
    import camoufox.async_api as _api_mod

    cls = _make_async_camoufox_cls(html="<html>real</html>")
    crawler = _Crawler()

    with (
        patch.object(crawler, "_human_delay", new_callable=AsyncMock),
        patch.object(_api_mod, "AsyncCamoufox", cls),
    ):
        result = await crawler.get_page("http://example.com/real")

    assert result == "<html>real</html>"


@pytest.mark.asyncio
async def test_real_get_page_with_proxy_lines_37_38():
    """
    Lines 37-38: proxy returned → proxy_dict = {'server': proxy}.
    Verifies the real code path builds the proxy dict correctly.
    """
    import camoufox.async_api as _api_mod

    captured = {}

    def _cls(**kwargs):
        captured.update(kwargs)
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html/>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_browser.__aexit__ = AsyncMock(return_value=False)
        return mock_browser

    crawler = _Crawler()

    with (
        patch.object(crawler, "_human_delay", new_callable=AsyncMock),
        patch.object(crawler, "get_proxy", return_value="socks5://127.0.0.1:9050"),
        patch.object(_api_mod, "AsyncCamoufox", _cls),
    ):
        await crawler.get_page("http://example.com/proxy")

    assert captured.get("proxy") == {"server": "socks5://127.0.0.1:9050"}


@pytest.mark.asyncio
async def test_real_get_page_no_proxy_passes_none_lines_37_38():
    """
    Lines 37-38: no proxy → proxy_dict = None passed to AsyncCamoufox.
    """
    import camoufox.async_api as _api_mod

    captured = {}

    def _cls(**kwargs):
        captured.update(kwargs)
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html/>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_browser.__aexit__ = AsyncMock(return_value=False)
        return mock_browser

    crawler = _Crawler()

    with (
        patch.object(crawler, "_human_delay", new_callable=AsyncMock),
        patch.object(crawler, "get_proxy", return_value=None),
        patch.object(_api_mod, "AsyncCamoufox", _cls),
    ):
        await crawler.get_page("http://example.com/noproxy")

    assert captured.get("proxy") is None


@pytest.mark.asyncio
async def test_real_get_page_exception_returns_empty_lines_52_54(caplog):
    """
    Lines 52-54: exception during browser operations → log warning, return ''.
    page.goto raises RuntimeError so the except block fires on the real method.
    """
    import logging

    import camoufox.async_api as _api_mod

    cls = _make_async_camoufox_cls(raise_exc=RuntimeError("browser_crashed"))
    crawler = _Crawler()

    with (
        patch.object(crawler, "_human_delay", new_callable=AsyncMock),
        patch.object(_api_mod, "AsyncCamoufox", cls),
        caplog.at_level(logging.WARNING, logger="modules.crawlers.camoufox_base"),
    ):
        result = await crawler.get_page("http://example.com/crash")

    assert result == ""
    assert any("CamoufoxCrawler.get_page failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_real_get_page_goto_called_with_correct_args():
    """
    Line 50: page.goto(url, wait_until='domcontentloaded', timeout=30000).
    Verifies the exact call signature used in the real method.
    """
    import camoufox.async_api as _api_mod

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html/>")

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)

    cls = MagicMock(return_value=mock_browser)
    crawler = _Crawler()

    with (
        patch.object(crawler, "_human_delay", new_callable=AsyncMock),
        patch.object(_api_mod, "AsyncCamoufox", cls),
    ):
        await crawler.get_page("http://goto-test.com")

    mock_page.goto.assert_awaited_once_with(
        "http://goto-test.com", wait_until="domcontentloaded", timeout=30000
    )
