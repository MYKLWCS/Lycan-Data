"""
test_flaresolverr_wave3.py — Coverage for flaresolverr_base.py.

Uncovered lines:
  44     positive health cache returns True immediately
  47-54  re-probe path: negative TTL expired → probe runs, sets _fs_healthy
  65-90  fs_get() when FlareSolverr IS available (happy path + error fallback)

All HTTP is mocked — no real network.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.flaresolverr_base import FlareSolverrCrawler


class _Crawler(FlareSolverrCrawler):
    platform = "test_fs"
    requires_tor = False

    async def scrape(self, identifier):
        return self._result(identifier, False)


def _reset_cache():
    """Reset class-level health cache before each test."""
    FlareSolverrCrawler._fs_healthy = None
    FlareSolverrCrawler._fs_checked_at = 0.0


# ---------------------------------------------------------------------------
# _probe_flaresolverr — line 44 (positive indefinite cache)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_positive_cache_returns_true_without_http():
    """_fs_healthy=True → returns True immediately, no HTTP call (line 44)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = True

    # If HTTP were made it would fail (no mock); the fact this returns True proves
    # the early-return at line 44 was taken.
    result = await FlareSolverrCrawler._probe_flaresolverr()
    assert result is True


# ---------------------------------------------------------------------------
# _probe_flaresolverr — lines 47-54 (negative TTL expired → re-probe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_negative_within_ttl_returns_false():
    """_fs_healthy=False and within TTL → returns False without HTTP (line 46)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = False
    FlareSolverrCrawler._fs_checked_at = time.monotonic()  # just set

    result = await FlareSolverrCrawler._probe_flaresolverr()
    assert result is False


@pytest.mark.asyncio
async def test_probe_negative_ttl_expired_re_probes_success():
    """_fs_healthy=False, TTL expired → HTTP probe runs, caches True (lines 47-53)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = False
    FlareSolverrCrawler._fs_checked_at = 0.0  # very old

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client):
        result = await FlareSolverrCrawler._probe_flaresolverr()

    assert result is True
    assert FlareSolverrCrawler._fs_healthy is True


@pytest.mark.asyncio
async def test_probe_negative_ttl_expired_re_probes_failure():
    """TTL expired, probe fails (non-200) → caches False (lines 47-53)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = False
    FlareSolverrCrawler._fs_checked_at = 0.0

    mock_resp = MagicMock()
    mock_resp.status_code = 503

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client):
        result = await FlareSolverrCrawler._probe_flaresolverr()

    assert result is False
    assert FlareSolverrCrawler._fs_healthy is False


@pytest.mark.asyncio
async def test_probe_exception_sets_healthy_false():
    """HTTP exception during probe → _fs_healthy=False (lines 51-52)."""
    _reset_cache()
    FlareSolverrCrawler._fs_checked_at = 0.0

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=OSError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client):
        result = await FlareSolverrCrawler._probe_flaresolverr()

    assert result is False
    assert FlareSolverrCrawler._fs_healthy is False


# ---------------------------------------------------------------------------
# fs_get — lines 65-90 (FlareSolverr available, happy path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fs_get_happy_path_returns_fs_response():
    """FlareSolverr UP → POST to /v1, parse solution, return _FsResponse (lines 65-85)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = True

    fs_response_data = {
        "status": "ok",
        "solution": {
            "response": "<html>cloudflare page</html>",
            "status": 200,
            "cookies": [{"name": "cf_clearance", "value": "abc123"}],
        },
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=fs_response_data)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    crawler = _Crawler()

    with patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client):
        result = await crawler.fs_get("http://cf-protected.com")

    assert result.text == "<html>cloudflare page</html>"
    assert result.status_code == 200
    assert result.cookies == {"cf_clearance": "abc123"}

    # Verify the payload sent to FlareSolverr
    call_kwargs = mock_client.post.call_args
    payload = (
        call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        if len(call_kwargs.args) > 1
        else call_kwargs.kwargs.get("json")
    )
    assert payload["cmd"] == "request.get"
    assert payload["url"] == "http://cf-protected.com"


@pytest.mark.asyncio
async def test_fs_get_status_not_ok_raises_and_falls_back():
    """FlareSolverr returns status != 'ok' → RuntimeError → fallback to curl (lines 75-76, 86-90)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = True

    bad_response = {"status": "error", "message": "challenge unsolved"}

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=bad_response)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    crawler = _Crawler()
    fallback_resp = MagicMock(text="<html/>", status_code=200)

    with (
        patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client),
        patch.object(
            crawler, "get", new_callable=AsyncMock, return_value=fallback_resp
        ) as mock_get,
    ):
        result = await crawler.fs_get("http://cf-protected.com")

    # Should have fallen back to CurlCrawler.get
    mock_get.assert_awaited_once_with("http://cf-protected.com")
    # Health cache should be marked False
    assert FlareSolverrCrawler._fs_healthy is False
    assert result is fallback_resp


@pytest.mark.asyncio
async def test_fs_get_http_exception_falls_back():
    """HTTP exception while calling FlareSolverr → fallback to curl (lines 86-90)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = True

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=OSError("connection reset"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    crawler = _Crawler()
    fallback_resp = MagicMock(text="<html/>", status_code=200)

    with (
        patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client),
        patch.object(
            crawler, "get", new_callable=AsyncMock, return_value=fallback_resp
        ) as mock_get,
    ):
        result = await crawler.fs_get("http://cf-protected.com")

    mock_get.assert_awaited_once()
    assert FlareSolverrCrawler._fs_healthy is False
    assert result is fallback_resp


@pytest.mark.asyncio
async def test_fs_get_cookies_empty_list():
    """Solution with no cookies → empty dict (line 83)."""
    _reset_cache()
    FlareSolverrCrawler._fs_healthy = True

    fs_response_data = {
        "status": "ok",
        "solution": {
            "response": "<html/>",
            "status": 200,
            "cookies": [],
        },
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=fs_response_data)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    crawler = _Crawler()

    with patch("modules.crawlers.flaresolverr_base.httpx.AsyncClient", return_value=mock_client):
        result = await crawler.fs_get("http://cf-protected.com")

    assert result.cookies == {}
