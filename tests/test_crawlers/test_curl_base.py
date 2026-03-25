import pytest

from modules.crawlers.curl_base import CurlCrawler


class _TestCrawler(CurlCrawler):
    platform = "test"
    async def scrape(self, identifier): return self._result(identifier, False)

@pytest.mark.asyncio
async def test_curl_crawler_is_httpx_subclass():
    from modules.crawlers.httpx_base import HttpxCrawler
    assert issubclass(CurlCrawler, HttpxCrawler)

@pytest.mark.asyncio
async def test_curl_crawler_instantiates():
    c = _TestCrawler()
    assert c is not None
