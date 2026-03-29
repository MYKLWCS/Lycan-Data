"""
Load test — 50 concurrent searches.

All external I/O is mocked. Tests verify:
  - No crash or deadlock under high concurrency
  - All 50 searches complete
  - No results are lost or mixed across concurrent runs
  - Semaphore limits are respected
  - Progress tracking stays consistent under concurrent updates

Run with:
    pytest tests/test_load_concurrent_search.py -v
"""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.core.orchestrator import ScraperOrchestrator
from modules.crawlers.core.result import CrawlerResult
from modules.pipeline.progress_tracker import ProgressAggregator
from shared.schemas.progress import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONCURRENT_SEARCHES = 50


class _CountingCrawler:
    """
    Fake crawler that records how many times it was invoked.
    Introduces a tiny async yield to simulate I/O.
    """

    def __init__(self, platform: str, search_id: str):
        self.platform = platform
        self._search_id = search_id

    async def run(self, identifier: str) -> CrawlerResult:
        await asyncio.sleep(0)  # yield to event loop
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"search_id": self._search_id, "full_name": identifier},
            source_reliability=0.9,
        )


async def _single_search(search_id: str, query: str) -> list[CrawlerResult]:
    """Run one search using three fake crawlers and return results."""
    crawlers = [
        _CountingCrawler(f"platform_{i}", search_id)
        for i in range(3)
    ]
    orchestrator = ScraperOrchestrator(concurrency=10, timeout=10.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        return await orchestrator.run_all(query)


# ===========================================================================
# Concurrency / load tests
# ===========================================================================


@pytest.mark.asyncio
async def test_50_concurrent_searches_all_complete():
    """
    Launch 50 searches simultaneously. Every single one must complete
    without raising an exception.
    """
    search_ids = [str(uuid.uuid4()) for _ in range(CONCURRENT_SEARCHES)]
    tasks = [
        asyncio.create_task(_single_search(sid, f"Person {i}"))
        for i, sid in enumerate(search_ids)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    assert errors == [], f"Exceptions from concurrent searches: {errors}"
    assert len(results) == CONCURRENT_SEARCHES


@pytest.mark.asyncio
async def test_50_concurrent_searches_return_correct_result_counts():
    """Each search returns exactly 3 results (one per fake crawler)."""
    search_ids = [str(uuid.uuid4()) for _ in range(CONCURRENT_SEARCHES)]
    tasks = [
        asyncio.create_task(_single_search(sid, f"Person {i}"))
        for i, sid in enumerate(search_ids)
    ]

    all_results = await asyncio.gather(*tasks)

    for i, results in enumerate(all_results):
        assert len(results) == 3, f"Search {i} returned {len(results)} results, expected 3"


@pytest.mark.asyncio
async def test_50_concurrent_searches_no_result_cross_contamination():
    """Results from one search must not bleed into another search."""
    search_ids = [str(uuid.uuid4()) for _ in range(CONCURRENT_SEARCHES)]
    tasks = [
        asyncio.create_task(_single_search(sid, f"Person {i}"))
        for i, sid in enumerate(search_ids)
    ]

    all_results = await asyncio.gather(*tasks)

    for i, (sid, results) in enumerate(zip(search_ids, all_results)):
        for r in results:
            assert r.data["search_id"] == sid, (
                f"Search {i} contains result with wrong search_id: "
                f"expected {sid}, got {r.data['search_id']}"
            )


@pytest.mark.asyncio
async def test_50_concurrent_searches_complete_within_time_limit():
    """50 searches with mocked crawlers complete in under 10 seconds."""
    search_ids = [str(uuid.uuid4()) for _ in range(CONCURRENT_SEARCHES)]

    t0 = time.monotonic()
    tasks = [
        asyncio.create_task(_single_search(sid, f"Person {i}"))
        for i, sid in enumerate(search_ids)
    ]
    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - t0

    # Should be near-instant with mocked crawlers, well under 10 s
    assert elapsed < 10.0, f"50 concurrent searches took {elapsed:.2f}s — possible deadlock"


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_crawler_invocations():
    """
    With concurrency=3 and 10 crawlers, no more than 3 crawlers should
    run simultaneously inside a single search.
    """
    max_concurrent = 0
    current = 0
    lock = asyncio.Lock()

    class _TrackedCrawler:
        def __init__(self, platform: str):
            self.platform = platform

        async def run(self, identifier: str) -> CrawlerResult:
            nonlocal max_concurrent, current
            async with lock:
                current += 1
                if current > max_concurrent:
                    max_concurrent = current
            await asyncio.sleep(0.01)  # hold slot briefly
            async with lock:
                current -= 1
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=True,
                data={},
            )

    crawlers = [_TrackedCrawler(f"p{i}") for i in range(10)]
    orchestrator = ScraperOrchestrator(concurrency=3, timeout=10.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        await orchestrator.run_all("John Doe")

    assert max_concurrent <= 3, (
        f"Semaphore violated: {max_concurrent} crawlers ran concurrently (limit=3)"
    )


@pytest.mark.asyncio
async def test_orchestrator_timeout_does_not_deadlock():
    """
    A crawler that hangs forever is cut off by the timeout.
    The orchestrator must return (not deadlock) within a reasonable time.
    """

    class _HangingCrawler:
        platform = "hanging_platform"

        async def run(self, identifier: str) -> CrawlerResult:
            await asyncio.sleep(999)  # effectively forever
            return CrawlerResult(platform=self.platform, identifier=identifier, found=False)

    crawlers = [_HangingCrawler()]
    # Short 0.1s timeout so the test completes quickly
    orchestrator = ScraperOrchestrator(concurrency=5, timeout=0.1)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        results = await asyncio.wait_for(
            orchestrator.run_all("John Doe"),
            timeout=5.0,
        )

    # Timed-out crawler is excluded from results
    assert results == []


@pytest.mark.asyncio
async def test_orchestrator_exception_in_one_crawler_does_not_stop_others():
    """
    If one crawler raises an exception, the remaining crawlers still complete.
    """

    class _FailingCrawler:
        platform = "failing"

        async def run(self, identifier: str) -> CrawlerResult:
            raise RuntimeError("network error")

    class _GoodCrawler:
        platform = "good"

        async def run(self, identifier: str) -> CrawlerResult:
            return CrawlerResult(platform="good", identifier=identifier, found=True, data={})

    crawlers = [_FailingCrawler(), _GoodCrawler(), _GoodCrawler()]
    orchestrator = ScraperOrchestrator(concurrency=5, timeout=5.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        results = await orchestrator.run_all("John Doe")

    # Only the good crawlers' results are returned (failing one returns None)
    assert len(results) == 2
    assert all(r.found for r in results)


@pytest.mark.asyncio
async def test_concurrent_progress_aggregators_are_isolated():
    """
    50 ProgressAggregator instances running concurrently must not share
    state — each tracks its own search.
    """
    SCRAPER_COUNT = 10

    async def _run_agg(search_id: str) -> ProgressAggregator:
        agg = ProgressAggregator(search_id, scraper_count=SCRAPER_COUNT)
        for i in range(SCRAPER_COUNT):
            await asyncio.sleep(0)  # yield
            agg.process({
                "event_type": EventType.SCRAPER_DONE,
                "scraper_name": f"scraper_{i}",
                "results_found": 1,
            })
        return agg

    search_ids = [str(uuid.uuid4()) for _ in range(CONCURRENT_SEARCHES)]
    aggs = await asyncio.gather(*[_run_agg(sid) for sid in search_ids])

    for sid, agg in zip(search_ids, aggs):
        assert agg.search_id == sid
        assert agg.scrapers_completed == SCRAPER_COUNT
        assert agg.results_found == SCRAPER_COUNT


@pytest.mark.asyncio
async def test_concurrent_searches_with_mixed_found_not_found():
    """
    50 concurrent searches where some scrapers return found=True,
    others found=False. Verify totals per search are consistent.
    """

    class _MixedCrawler:
        def __init__(self, platform: str, found: bool):
            self.platform = platform
            self._found = found

        async def run(self, identifier: str) -> CrawlerResult:
            await asyncio.sleep(0)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=self._found,
                data={},
            )

    async def _mixed_search(_sid: str) -> list[CrawlerResult]:
        crawlers = [
            _MixedCrawler("found_platform", True),
            _MixedCrawler("not_found_platform", False),
        ]
        orchestrator = ScraperOrchestrator(concurrency=5, timeout=5.0)
        with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
            return await orchestrator.run_all("John Doe")

    tasks = [asyncio.create_task(_mixed_search(str(uuid.uuid4()))) for _ in range(CONCURRENT_SEARCHES)]
    all_results = await asyncio.gather(*tasks)

    for results in all_results:
        assert len(results) == 2
        found_count = sum(1 for r in results if r.found)
        not_found_count = sum(1 for r in results if not r.found)
        assert found_count == 1
        assert not_found_count == 1


@pytest.mark.asyncio
async def test_no_deadlock_with_all_crawlers_raising_exceptions():
    """
    If every crawler raises, the orchestrator must still return (not hang).
    """

    class _AllFailing:
        def __init__(self, platform: str):
            self.platform = platform

        async def run(self, identifier: str) -> CrawlerResult:
            raise RuntimeError("all broken")

    crawlers = [_AllFailing(f"broken_{i}") for i in range(20)]
    orchestrator = ScraperOrchestrator(concurrency=5, timeout=2.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        results = await asyncio.wait_for(
            orchestrator.run_all("John Doe"),
            timeout=15.0,
        )

    assert results == []
