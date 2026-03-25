import pytest
from unittest.mock import AsyncMock, patch
from modules.crawlers.flaresolverr_base import FlareSolverrCrawler

class _TestCrawler(FlareSolverrCrawler):
    platform = "test"
    async def scrape(self, identifier): return self._result(identifier, False)

def test_flaresolverr_is_curl_subclass():
    from modules.crawlers.curl_base import CurlCrawler
    assert issubclass(FlareSolverrCrawler, CurlCrawler)

def test_health_cache_is_class_level():
    assert hasattr(FlareSolverrCrawler, "_fs_healthy")
    assert hasattr(FlareSolverrCrawler, "_fs_checked_at")

@pytest.mark.asyncio
async def test_fs_get_falls_back_when_unavailable():
    FlareSolverrCrawler._fs_healthy = False
    FlareSolverrCrawler._fs_checked_at = float("inf")
    c = _TestCrawler()
    with patch.object(c, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = AsyncMock(text="<html/>", status_code=200)
        result = await c.fs_get("http://example.com")
        mock_get.assert_called_once()
