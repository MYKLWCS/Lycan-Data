import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.base import BaseCrawler, MAX_SCRAPER_RETRIES
from modules.crawlers.registry import (
    CRAWLER_REGISTRY,
    get_crawler,
    is_registered,
    list_platforms,
    register,
)
from modules.crawlers.core.result import CrawlerResult

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
    from shared.config import settings

    @register("killtestplatform")
    class KillCrawler(BaseCrawler):
        platform = "killtestplatform"

        async def scrape(self, identifier: str) -> CrawlerResult:
            return self._result(identifier, found=True)

    crawler = KillCrawler()
    mock_settings = MagicMock(spec=settings)
    mock_settings.tor_enabled = settings.tor_enabled
    mock_settings.enable_killtestplatform = False
    with patch("modules.crawlers.base.settings", mock_settings):
        result = await crawler.run("testuser")
    assert result.found is False
    assert "kill switch" in result.error


@pytest.mark.asyncio
async def test_crawler_run_catches_exception():
    """run() catches exceptions from scrape() and returns error result after retries."""

    @register("errortestplatform")
    class ErrorCrawler(BaseCrawler):
        platform = "errortestplatform"
        max_retries = 1  # single attempt for speed

        async def scrape(self, identifier: str) -> CrawlerResult:
            raise ValueError("Test error")

    crawler = ErrorCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_success = AsyncMock()
    mock_cb.record_failure = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
    ):
        result = await crawler.run("testuser")
    assert result.found is False
    assert "Test error" in result.error


# --- Circuit breaker tests ---


@pytest.mark.asyncio
async def test_circuit_breaker_skips_when_open():
    """When circuit is open, run() returns immediately without scraping."""

    @register("cb_open_test")
    class CBOpenCrawler(BaseCrawler):
        platform = "cb_open_test"

        async def scrape(self, identifier: str) -> CrawlerResult:
            return self._result(identifier, found=True)

    crawler = CBOpenCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=True)

    with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
        result = await crawler.run("testuser")

    assert result.found is False
    assert "circuit_open" in result.error
    mock_cb.is_open.assert_called_once_with("cb_open_test")


@pytest.mark.asyncio
async def test_circuit_breaker_records_success():
    """Successful scrape records success with circuit breaker."""

    @register("cb_success_test")
    class CBSuccessCrawler(BaseCrawler):
        platform = "cb_success_test"

        async def scrape(self, identifier: str) -> CrawlerResult:
            return self._result(identifier, found=True)

    crawler = CBSuccessCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_success = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
    ):
        result = await crawler.run("testuser")

    assert result.found is True
    mock_cb.record_success.assert_called_once_with("cb_success_test")


@pytest.mark.asyncio
async def test_circuit_breaker_records_failure():
    """Failed scrape records failure with circuit breaker."""

    @register("cb_fail_test")
    class CBFailCrawler(BaseCrawler):
        platform = "cb_fail_test"
        max_retries = 1

        async def scrape(self, identifier: str) -> CrawlerResult:
            raise RuntimeError("connection refused")

    crawler = CBFailCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_failure = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
    ):
        result = await crawler.run("testuser")

    assert result.found is False
    mock_cb.record_failure.assert_called_once_with("cb_fail_test")


# --- Retry with backoff tests ---


@pytest.mark.asyncio
async def test_retry_on_exception():
    """run() retries on exception up to max_retries."""
    call_count = 0

    @register("retry_test")
    class RetryCrawler(BaseCrawler):
        platform = "retry_test"
        max_retries = 3

        async def scrape(self, identifier: str) -> CrawlerResult:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("timeout")
            return self._result(identifier, found=True)

    crawler = RetryCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_success = AsyncMock()
    mock_cb.record_failure = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
        patch("modules.crawlers.base.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await crawler.run("testuser")

    assert result.found is True
    assert call_count == 3  # failed twice, succeeded on third
    assert mock_cb.record_failure.call_count == 2
    assert mock_cb.record_success.call_count == 1


@pytest.mark.asyncio
async def test_all_retries_exhausted():
    """When all retries fail, returns error result."""

    @register("exhaust_test")
    class ExhaustCrawler(BaseCrawler):
        platform = "exhaust_test"
        max_retries = 2

        async def scrape(self, identifier: str) -> CrawlerResult:
            raise TimeoutError("always fails")

    crawler = ExhaustCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_failure = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
        patch("modules.crawlers.base.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await crawler.run("testuser")

    assert result.found is False
    assert "always fails" in result.error
    assert mock_cb.record_failure.call_count == 2


# --- Structured logging tests ---


@pytest.mark.asyncio
async def test_structured_error_logging(caplog):
    """Scraper errors are logged with structured fields."""
    import logging

    @register("log_test")
    class LogCrawler(BaseCrawler):
        platform = "log_test"
        max_retries = 1

        async def scrape(self, identifier: str) -> CrawlerResult:
            raise ValueError("parse error")

    crawler = LogCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_failure = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
        caplog.at_level(logging.ERROR, logger="modules.crawlers.base"),
    ):
        await crawler.run("john@example.com")

    # Check structured fields in log output
    error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_logs) >= 1
    log_msg = error_logs[0].message
    assert "source=log_test" in log_msg
    assert "identifier=john@example.com" in log_msg
    assert "error_type=ValueError" in log_msg
    assert "parse error" in log_msg


@pytest.mark.asyncio
async def test_success_logging(caplog):
    """Successful scrapes are logged with structured fields."""
    import logging

    @register("success_log_test")
    class SuccessLogCrawler(BaseCrawler):
        platform = "success_log_test"

        async def scrape(self, identifier: str) -> CrawlerResult:
            return self._result(identifier, found=True)

    crawler = SuccessLogCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open = AsyncMock(return_value=False)
    mock_cb.record_success = AsyncMock()

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("modules.crawlers.base.BaseCrawler._human_delay", new_callable=AsyncMock),
        caplog.at_level(logging.INFO, logger="modules.crawlers.base"),
    ):
        await crawler.run("testuser")

    info_logs = [r for r in caplog.records if "scraper_success" in r.message]
    assert len(info_logs) == 1
    assert "source=success_log_test" in info_logs[0].message
    assert "found=True" in info_logs[0].message


def test_max_retries_constant():
    """MAX_SCRAPER_RETRIES is a reasonable value."""
    assert MAX_SCRAPER_RETRIES >= 1
    assert MAX_SCRAPER_RETRIES <= 10
