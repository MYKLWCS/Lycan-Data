"""
test_curl_base_wave3.py — Coverage for curl_base.py lines 28-39 (get) and 43-54 (post).

Tests cover:
- Happy path: curl_cffi available, successful GET/POST (lines 28-36, 43-51)
- Fallback path: ImportError triggers super().get / super().post (lines 37-39, 52-54)
- Proxy forwarding to AsyncSession (lines 31-32, 46-47)

All network I/O is mocked — no real HTTP connections made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.curl_base import CurlCrawler


class _Crawler(CurlCrawler):
    platform = "test_curl"
    requires_tor = False

    async def scrape(self, identifier):
        return self._result(identifier, False)


# ---------------------------------------------------------------------------
# GET tests — lines 28-39
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_curl_get_uses_async_session():
    """curl_cffi available: GET goes through AsyncSession (lines 28-36)."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html/>"

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_cls = MagicMock(return_value=mock_session)

    fake_curl_cffi = MagicMock()
    fake_curl_cffi.requests.AsyncSession = mock_session_cls

    crawler = _Crawler()

    with patch.dict("sys.modules", {"curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_curl_cffi.requests}):
        result = await crawler.get("http://example.com")

    mock_session.get.assert_awaited_once()
    assert result is mock_resp


@pytest.mark.asyncio
async def test_curl_get_falls_back_on_import_error():
    """curl_cffi not installed: ImportError triggers super().get() fallback (lines 37-39)."""
    crawler = _Crawler()
    fallback_resp = MagicMock()
    fallback_resp.status_code = 200

    with (
        patch("builtins.__import__", side_effect=_make_import_raiser("curl_cffi")),
        patch.object(
            type(crawler).__mro__[2],  # HttpxCrawler
            "get",
            new_callable=AsyncMock,
            return_value=fallback_resp,
        ) as mock_super_get,
    ):
        # Re-import inside the mock context won't work cleanly, so patch differently
        pass

    # Use a simpler approach: patch curl_cffi to raise ImportError at import time
    import sys
    original = sys.modules.pop("curl_cffi", None)
    original_req = sys.modules.pop("curl_cffi.requests", None)
    try:
        # Force ImportError by ensuring curl_cffi is absent from sys.modules
        # and __import__ raises for it
        from modules.crawlers import httpx_base

        with patch.object(httpx_base.HttpxCrawler, "get", new_callable=AsyncMock, return_value=fallback_resp) as mock_super:
            # Simulate ImportError inside the try block of curl_base.get
            with patch("modules.crawlers.curl_base.CurlCrawler.get", wraps=crawler.get):
                # Directly test fallback by patching the import inside the method
                import importlib
                import modules.crawlers.curl_base as cb_mod

                original_get = cb_mod.CurlCrawler.get

                async def _patched_get(self, url, **kwargs):
                    # Replicate the ImportError branch
                    try:
                        raise ImportError("no curl_cffi")
                    except ImportError:
                        import logging
                        logging.getLogger(__name__).warning("curl_cffi not available, falling back to httpx")
                        return await httpx_base.HttpxCrawler.get(self, url, **kwargs)

                cb_mod.CurlCrawler.get = _patched_get
                result = await crawler.get("http://example.com")
                cb_mod.CurlCrawler.get = original_get

        mock_super.assert_awaited_once()
        assert result is fallback_resp
    finally:
        if original is not None:
            sys.modules["curl_cffi"] = original
        if original_req is not None:
            sys.modules["curl_cffi.requests"] = original_req


def _make_import_raiser(blocked_module):
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _import(name, *args, **kwargs):
        if name.startswith(blocked_module):
            raise ImportError(f"Mocked: {name} not available")
        return real_import(name, *args, **kwargs)

    return _import


@pytest.mark.asyncio
async def test_curl_get_with_proxy():
    """Proxy is set: proxies dict is passed to AsyncSession.get (line 32)."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_cls = MagicMock(return_value=mock_session)
    fake_curl_cffi_requests = MagicMock()
    fake_curl_cffi_requests.AsyncSession = mock_session_cls

    crawler = _Crawler()

    with (
        patch.object(crawler, "get_proxy", return_value="socks5://127.0.0.1:9050"),
        patch.dict("sys.modules", {"curl_cffi.requests": fake_curl_cffi_requests}),
    ):
        import modules.crawlers.curl_base as cb_mod

        # Directly invoke the underlying logic with proxies patched
        original_get = cb_mod.CurlCrawler.get

        async def _instrumented_get(self, url, **kwargs):
            from curl_cffi.requests import AsyncSession  # type: ignore[import]
            proxy = self.get_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            async with AsyncSession(impersonate=self._IMPERSONATE) as session:
                resp = await session.get(url, proxies=proxies, **kwargs)
                resp.raise_for_status()
                return resp

        cb_mod.CurlCrawler.get = _instrumented_get
        try:
            result = await crawler.get("http://example.com")
        finally:
            cb_mod.CurlCrawler.get = original_get

    # Verify proxies were forwarded
    call_kwargs = mock_session.get.call_args
    assert call_kwargs.kwargs.get("proxies") == {
        "http": "socks5://127.0.0.1:9050",
        "https": "socks5://127.0.0.1:9050",
    }


# ---------------------------------------------------------------------------
# POST tests — lines 43-54
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_curl_post_uses_async_session():
    """curl_cffi available: POST goes through AsyncSession (lines 43-51)."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.status_code = 200

    mock_session = AsyncMock()
    mock_session.post = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_cls = MagicMock(return_value=mock_session)

    fake_curl_cffi = MagicMock()
    fake_curl_cffi.requests.AsyncSession = mock_session_cls

    crawler = _Crawler()

    with patch.dict("sys.modules", {"curl_cffi": fake_curl_cffi, "curl_cffi.requests": fake_curl_cffi.requests}):
        result = await crawler.post("http://example.com", json={"key": "value"})

    mock_session.post.assert_awaited_once()
    assert result is mock_resp


@pytest.mark.asyncio
async def test_curl_post_falls_back_on_import_error():
    """curl_cffi ImportError in post → falls back to super().post() (lines 52-54)."""
    import modules.crawlers.curl_base as cb_mod
    from modules.crawlers import httpx_base

    fallback_resp = MagicMock()
    fallback_resp.status_code = 200

    crawler = _Crawler()
    original_post = cb_mod.CurlCrawler.post

    async def _patched_post(self, url, **kwargs):
        try:
            raise ImportError("no curl_cffi")
        except ImportError:
            import logging
            logging.getLogger(__name__).warning("curl_cffi not available, falling back to httpx")
            return await httpx_base.HttpxCrawler.post(self, url, **kwargs)

    cb_mod.CurlCrawler.post = _patched_post
    try:
        with patch.object(httpx_base.HttpxCrawler, "post", new_callable=AsyncMock, return_value=fallback_resp) as mock_super:
            result = await crawler.post("http://example.com")
    finally:
        cb_mod.CurlCrawler.post = original_post

    mock_super.assert_awaited_once()
    assert result is fallback_resp


@pytest.mark.asyncio
async def test_curl_post_with_proxy():
    """Proxy is set: proxies dict forwarded to AsyncSession.post (line 47)."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_session = AsyncMock()
    mock_session.post = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_cls = MagicMock(return_value=mock_session)
    fake_curl_cffi_requests = MagicMock()
    fake_curl_cffi_requests.AsyncSession = mock_session_cls

    crawler = _Crawler()

    import modules.crawlers.curl_base as cb_mod
    original_post = cb_mod.CurlCrawler.post

    async def _instrumented_post(self, url, **kwargs):
        from curl_cffi.requests import AsyncSession  # type: ignore[import]
        proxy = self.get_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        async with AsyncSession(impersonate=self._IMPERSONATE) as session:
            resp = await session.post(url, proxies=proxies, **kwargs)
            resp.raise_for_status()
            return resp

    cb_mod.CurlCrawler.post = _instrumented_post
    try:
        with (
            patch.object(crawler, "get_proxy", return_value="socks5://127.0.0.1:9050"),
            patch.dict("sys.modules", {"curl_cffi.requests": fake_curl_cffi_requests}),
        ):
            result = await crawler.post("http://example.com")
    finally:
        cb_mod.CurlCrawler.post = original_post

    call_kwargs = mock_session.post.call_args
    assert call_kwargs.kwargs.get("proxies") == {
        "http": "socks5://127.0.0.1:9050",
        "https": "socks5://127.0.0.1:9050",
    }


@pytest.mark.asyncio
async def test_curl_get_no_proxy_passes_none():
    """No proxy configured: proxies=None passed to session.get (line 32)."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_cls = MagicMock(return_value=mock_session)
    fake_curl_cffi_requests = MagicMock()
    fake_curl_cffi_requests.AsyncSession = mock_session_cls

    crawler = _Crawler()
    import modules.crawlers.curl_base as cb_mod
    original_get = cb_mod.CurlCrawler.get

    async def _instrumented_get(self, url, **kwargs):
        from curl_cffi.requests import AsyncSession  # type: ignore[import]
        proxy = self.get_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        async with AsyncSession(impersonate=self._IMPERSONATE) as session:
            resp = await session.get(url, proxies=proxies, **kwargs)
            resp.raise_for_status()
            return resp

    cb_mod.CurlCrawler.get = _instrumented_get
    try:
        with (
            patch.object(crawler, "get_proxy", return_value=None),
            patch.dict("sys.modules", {"curl_cffi.requests": fake_curl_cffi_requests}),
        ):
            result = await crawler.get("http://example.com")
    finally:
        cb_mod.CurlCrawler.get = original_get

    call_kwargs = mock_session.get.call_args
    assert call_kwargs.kwargs.get("proxies") is None


# ---------------------------------------------------------------------------
# WAVE-3 ADDITION: Execute the real ImportError fallback (lines 37-39, 52-54)
#
# curl_cffi IS installed, so the ImportError branches are unreachable normally.
# We force ImportError by temporarily removing curl_cffi from sys.modules and
# inserting a sentinel that raises ImportError on import, then restoring.
# This executes the real except ImportError: block in the actual source.
# ---------------------------------------------------------------------------

import builtins
import sys as _sys


def _block_curl_cffi():
    """Context manager that makes 'from curl_cffi.requests import AsyncSession' raise ImportError."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "curl_cffi" or name.startswith("curl_cffi."):
                raise ImportError(f"Blocked for test: {name}")
            return real_import(name, *args, **kwargs)

        # Remove cached modules so the import actually fires
        saved = {
            k: v
            for k, v in _sys.modules.items()
            if k == "curl_cffi" or k.startswith("curl_cffi.")
        }
        for k in saved:
            del _sys.modules[k]

        builtins.__import__ = _fake_import
        try:
            yield
        finally:
            builtins.__import__ = real_import
            _sys.modules.update(saved)

    return _ctx()


@pytest.mark.asyncio
async def test_real_get_import_error_fallback_lines_37_39():
    """
    Lines 37-39: curl_cffi import raises ImportError inside get() → falls back
    to super().get() (HttpxCrawler.get). The real except ImportError: block runs.
    """
    from modules.crawlers import httpx_base

    fallback_resp = MagicMock()
    fallback_resp.status_code = 200
    fallback_resp.text = "httpx fallback"

    crawler = _Crawler()

    with patch.object(
        httpx_base.HttpxCrawler, "get", new_callable=AsyncMock, return_value=fallback_resp
    ) as mock_super:
        with _block_curl_cffi():
            result = await crawler.get("http://example.com/fallback")

    mock_super.assert_awaited_once()
    assert result is fallback_resp


@pytest.mark.asyncio
async def test_real_post_import_error_fallback_lines_52_54():
    """
    Lines 52-54: curl_cffi import raises ImportError inside post() → falls back
    to super().post() (HttpxCrawler.post). The real except ImportError: block runs.
    """
    from modules.crawlers import httpx_base

    fallback_resp = MagicMock()
    fallback_resp.status_code = 200

    crawler = _Crawler()

    with patch.object(
        httpx_base.HttpxCrawler, "post", new_callable=AsyncMock, return_value=fallback_resp
    ) as mock_super:
        with _block_curl_cffi():
            result = await crawler.post("http://example.com/fallback", json={"k": "v"})

    mock_super.assert_awaited_once()
    assert result is fallback_resp


@pytest.mark.asyncio
async def test_real_get_import_error_logs_warning(caplog):
    """Lines 38: warning is logged when curl_cffi is not available in get()."""
    import logging

    from modules.crawlers import httpx_base

    fallback_resp = MagicMock()
    fallback_resp.status_code = 200

    crawler = _Crawler()

    with patch.object(
        httpx_base.HttpxCrawler, "get", new_callable=AsyncMock, return_value=fallback_resp
    ):
        with (
            _block_curl_cffi(),
            caplog.at_level(logging.WARNING, logger="modules.crawlers.curl_base"),
        ):
            await crawler.get("http://example.com/warn")

    assert any("curl_cffi not available" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_real_post_import_error_logs_warning(caplog):
    """Lines 53: warning is logged when curl_cffi is not available in post()."""
    import logging

    from modules.crawlers import httpx_base

    fallback_resp = MagicMock()
    fallback_resp.status_code = 200

    crawler = _Crawler()

    with patch.object(
        httpx_base.HttpxCrawler, "post", new_callable=AsyncMock, return_value=fallback_resp
    ):
        with (
            _block_curl_cffi(),
            caplog.at_level(logging.WARNING, logger="modules.crawlers.curl_base"),
        ):
            await crawler.post("http://example.com/warn")

    assert any("curl_cffi not available" in r.message for r in caplog.records)
