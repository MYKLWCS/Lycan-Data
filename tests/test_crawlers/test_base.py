import pytest
from modules.crawlers.registry import register, get_crawler, list_platforms, is_registered, CRAWLER_REGISTRY
from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult


# --- Registry tests ---

def test_register_decorator():
    @register("testplatform")
    class TestCrawler(BaseCrawler):
        platform = "testplatform"
        async def scrape(self, identifier: str) -> CrawlerResult:
            return self._result(identifier, found=True, handle=identifier)

    assert is_registered("testplatform")
    assert get_crawler("testplatform") is TestCrawler


def test_get_crawler_case_insensitive():
    assert get_crawler("TESTPLATFORM") == get_crawler("testplatform")


def test_list_platforms_sorted():
    platforms = list_platforms()
    assert platforms == sorted(platforms)


def test_get_crawler_unknown_returns_none():
    assert get_crawler("does_not_exist_xyz") is None


# --- CrawlerResult tests ---

def test_crawler_result_defaults():
    r = CrawlerResult(platform="instagram", identifier="testuser", found=True)
    assert r.tor_used is False
    assert r.error is None
    assert r.source_reliability == 0.5


def test_crawler_result_to_db_dict():
    r = CrawlerResult(
        platform="instagram",
        identifier="natgeo",
        found=True,
        data={"handle": "natgeo", "follower_count": 1000000, "is_verified": True},
        profile_url="https://instagram.com/natgeo/",
        source_reliability=0.55,
    )
    d = r.to_db_dict()
    assert d["handle"] == "natgeo"
    assert d["follower_count"] == 1000000
    assert d["is_verified"] is True
    assert d["source_reliability"] == 0.55


# --- BaseCrawler kill switch test ---

@pytest.mark.asyncio
async def test_crawler_run_kill_switch():
    """If kill switch is off, run() returns not-found without scraping."""
    from unittest.mock import patch, MagicMock
    from shared.config import settings

    @register("killtestplatform")
    class KillCrawler(BaseCrawler):
        platform = "killtestplatform"
        async def scrape(self, identifier: str) -> CrawlerResult:
            return self._result(identifier, found=True)

    crawler = KillCrawler()
    # Pydantic v2 BaseSettings is frozen — replace the whole settings object in base module.
    # hasattr(mock, "enable_killtestplatform") returns True by default on MagicMock;
    # we set it to False so the kill switch fires.
    mock_settings = MagicMock(spec=settings)
    mock_settings.tor_enabled = settings.tor_enabled
    mock_settings.enable_killtestplatform = False
    with patch("modules.crawlers.base.settings", mock_settings):
        result = await crawler.run("testuser")
    assert result.found is False
    assert "kill switch" in result.error


@pytest.mark.asyncio
async def test_crawler_run_catches_exception():
    """run() catches exceptions from scrape() and returns error result."""
    @register("errortestplatform")
    class ErrorCrawler(BaseCrawler):
        platform = "errortestplatform"
        async def scrape(self, identifier: str) -> CrawlerResult:
            raise ValueError("Test error")

    crawler = ErrorCrawler()
    result = await crawler.run("testuser")
    assert result.found is False
    assert "Test error" in result.error
