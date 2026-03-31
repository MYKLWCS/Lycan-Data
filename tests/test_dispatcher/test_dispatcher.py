"""
Tests for the Crawl Job Dispatcher.
Covers routing, status updates, retries, error handling, enqueueing,
and concurrent execution via semaphore.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.core.result import CrawlerResult
from modules.dispatcher.dispatcher import (
    CONCURRENCY_PER_WORKER,
    MAX_RETRIES,
    RETRY_DELAYS,
    CrawlDispatcher,
    dispatch_job,
)
from shared.constants import CrawlStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job_dict(**kwargs) -> dict:
    base = {
        "job_id": "job-abc-123",
        "platform": "instagram",
        "identifier": "testuser",
        "person_id": "person-xyz",
        "retry_count": 0,
    }
    base.update(kwargs)
    return base


def _make_result(
    found: bool = True, error: str | None = None, platform: str = "instagram"
) -> CrawlerResult:
    return CrawlerResult(
        platform=platform,
        identifier="testuser",
        found=found,
        data={"handle": "testuser", "display_name": "Test User"},
        error=error,
        source_reliability=0.75,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatcher():
    return CrawlDispatcher(worker_id="test-worker")


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# 1. job routed to the correct crawler
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_routes_to_correct_crawler(dispatcher, mock_session):
    """_process_one should route the job to the registered crawler."""
    job_dict = _make_job_dict()
    found_result = _make_result(found=True)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_crawler_inst.run.assert_called_once_with("testuser")


# ---------------------------------------------------------------------------
# 2. no crawler found -> FAILED status set
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_crawler_sets_failed_status(dispatcher, mock_session):
    """When no crawler is registered for a platform, job is marked FAILED."""
    job_dict = _make_job_dict(platform="nonexistent_platform")

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=None),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_session.execute.assert_called()
    mock_session.commit.assert_called()


# ---------------------------------------------------------------------------
# 3. crawler returns found=True -> DONE + ingest enqueued
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_found_result_triggers_ingest_and_done(dispatcher, mock_session):
    """found=True result should enqueue to ingest queue and set DONE."""
    job_dict = _make_job_dict()
    found_result = _make_result(found=True)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    ingest_calls = [c for c in mock_bus.enqueue.call_args_list if c[1].get("priority") == "ingest"]
    assert len(ingest_calls) == 1


# ---------------------------------------------------------------------------
# 4. rate_limited error -> RATE_LIMITED + requeued
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_limited_error_sets_rate_limited_and_requeues(dispatcher, mock_session):
    """When error contains 'rate', status -> RATE_LIMITED and job is requeued."""
    job_dict = _make_job_dict()
    rate_limited_result = _make_result(found=False, error="rate limit exceeded")

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=rate_limited_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_bus.enqueue.assert_called_once()
    enqueue_call_args = mock_bus.enqueue.call_args
    assert enqueue_call_args[1]["priority"] == "normal"


# ---------------------------------------------------------------------------
# 5. blocked error -> BLOCKED status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_blocked_error_sets_blocked_status(dispatcher, mock_session):
    """When error contains 'block', status -> BLOCKED, no requeue."""
    job_dict = _make_job_dict()
    blocked_result = _make_result(found=False, error="account blocked by platform")

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=blocked_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_bus.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 6. exception during crawl -> FAILED, retried if retry_count < MAX_RETRIES
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exception_causes_failed_and_retry(dispatcher, mock_session):
    """Exceptions during crawl -> FAILED status + requeue when retry_count < MAX_RETRIES."""
    job_dict = _make_job_dict(retry_count=0)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(side_effect=RuntimeError("network timeout"))
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_bus.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# 7. retry_count >= MAX_RETRIES -> no requeue, still FAILED
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_max_retries_exceeded_no_requeue(dispatcher, mock_session):
    """When retry_count >= MAX_RETRIES, exception -> FAILED with no requeue."""
    job_dict = _make_job_dict(retry_count=MAX_RETRIES)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(side_effect=RuntimeError("still failing"))
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_bus.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 8. invalid JSON payload -> skipped gracefully
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_json_payload_is_skipped(dispatcher):
    """Non-JSON or unparseable payloads are logged and skipped without crash."""
    await dispatcher._process_one("not valid json {{{{")
    # No further processing -- no DB calls, no errors propagated


# ---------------------------------------------------------------------------
# 9. dispatch_job enqueues correct payload
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_job_enqueues_correct_payload():
    """dispatch_job should push the right keys to the event bus."""
    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.enqueue = AsyncMock()

        await dispatch_job(
            platform="linkedin",
            identifier="john-doe",
            person_id="person-001",
            priority="high",
            job_id="job-999",
        )

    mock_bus.enqueue.assert_called_once()
    payload, kwargs = mock_bus.enqueue.call_args[0][0], mock_bus.enqueue.call_args[1]
    assert payload["platform"] == "linkedin"
    assert payload["identifier"] == "john-doe"
    assert payload["person_id"] == "person-001"
    assert payload["job_id"] == "job-999"
    assert payload["retry_count"] == 0
    assert kwargs["priority"] == "high"


# ---------------------------------------------------------------------------
# 10. dispatch_job uses default priority "normal"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_job_default_priority():
    """dispatch_job defaults to normal priority when not specified."""
    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.enqueue = AsyncMock()

        await dispatch_job(platform="twitter", identifier="@user")

    kwargs = mock_bus.enqueue.call_args[1]
    assert kwargs["priority"] == "normal"


# ---------------------------------------------------------------------------
# 11. _requeue_with_backoff uses correct delay and priority for retry_count=0
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_requeue_backoff_first_retry():
    """retry_count=0 -> delay=30s, priority=normal."""
    dispatcher = CrawlDispatcher()
    job_dict = _make_job_dict()

    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.enqueue = AsyncMock()

        await dispatcher._requeue_with_backoff(job_dict, retry_count=0)

    mock_bus.enqueue.assert_called_once()
    enqueued_job = mock_bus.enqueue.call_args[0][0]
    assert enqueued_job["retry_count"] == 1
    assert enqueued_job["run_after"] == pytest.approx(
        datetime.now(UTC).timestamp() + RETRY_DELAYS[0], abs=2
    )
    assert mock_bus.enqueue.call_args[1]["priority"] == "normal"


# ---------------------------------------------------------------------------
# 12. _requeue_with_backoff uses low priority for retry_count >= 1
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_requeue_backoff_second_retry_uses_low_priority():
    """retry_count=1 -> delay=120s, priority=low."""
    dispatcher = CrawlDispatcher()
    job_dict = _make_job_dict()

    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.enqueue = AsyncMock()

        await dispatcher._requeue_with_backoff(job_dict, retry_count=1)

    assert mock_bus.enqueue.call_args[1]["priority"] == "low"
    enqueued_job = mock_bus.enqueue.call_args[0][0]
    assert enqueued_job["retry_count"] == 2
    assert enqueued_job["run_after"] == pytest.approx(
        datetime.now(UTC).timestamp() + RETRY_DELAYS[1], abs=2
    )


# ---------------------------------------------------------------------------
# 13. dequeue_any returning None -> _process_one_guarded handles gracefully
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_returns_when_queue_empty(dispatcher):
    """When dequeue_any returns None, the dispatcher does nothing."""
    with patch("modules.dispatcher.dispatcher.get_crawler") as mock_get_crawler:
        # _process_one with None raw should just return
        await dispatcher._process_one(None)

    # get_crawler is not called because job_dict parsing fails on None
    # The function should handle this gracefully


# ---------------------------------------------------------------------------
# 14. found=True -> enrichment event published with correct fields
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_found_result_publishes_enrichment_event(dispatcher, mock_session):
    """On successful crawl, an enrichment event is published."""
    job_dict = _make_job_dict(platform="facebook", identifier="fb_user", person_id="pid-42")
    found_result = _make_result(found=True, platform="facebook")

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    # Dispatcher now also publishes progress events (SCRAPER_RUNNING, SCRAPER_DONE),
    # so assert that the enrichment event was published among all calls.
    enrichment_calls = [
        call for call in mock_bus.publish.call_args_list if call[0][0] == "enrichment"
    ]
    assert len(enrichment_calls) == 1
    channel, event = enrichment_calls[0][0]
    assert channel == "enrichment"
    assert event["event"] == "crawl_complete"
    assert event["platform"] == "facebook"
    assert event["person_id"] == "pid-42"
    assert event["found"] is True


# ---------------------------------------------------------------------------
# 15. not-found result with no error -> status set to DONE, no requeue
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_not_found_no_error_sets_done(dispatcher, mock_session):
    """found=False with no error -> DONE status, no retry, no event published."""
    job_dict = _make_job_dict()
    not_found_result = _make_result(found=False, error=None)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=not_found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        await dispatcher._process_one(job_dict)

    mock_bus.enqueue.assert_not_called()
    # Dispatcher publishes progress events even on not-found, but no enrichment event
    enrichment_calls = [
        call for call in mock_bus.publish.call_args_list if call[0][0] == "enrichment"
    ]
    assert len(enrichment_calls) == 0


# ---------------------------------------------------------------------------
# 16. Concurrent execution — semaphore limits parallelism
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_execution_with_semaphore():
    """Multiple jobs run concurrently up to the semaphore limit."""
    concurrency = 3
    dispatcher = CrawlDispatcher(worker_id="test-concurrent", concurrency=concurrency)

    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def _slow_run(identifier):
        nonlocal active_count, max_active
        async with lock:
            active_count += 1
            max_active = max(max_active, active_count)
        await asyncio.sleep(0.05)  # simulate work
        async with lock:
            active_count -= 1
        return CrawlerResult(platform="testplat", identifier=identifier, found=True, data={})

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = MagicMock()
    mock_crawler_inst.run = _slow_run
    mock_crawler_cls.return_value = mock_crawler_inst

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    jobs = [_make_job_dict(job_id=f"job-{i}", platform="testplat") for i in range(6)]

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()

        # Simulate what start() does: acquire semaphore, then spawn guarded task
        tasks = []
        for job in jobs:
            await dispatcher._semaphore.acquire()
            tasks.append(asyncio.create_task(dispatcher._process_one_guarded(job)))
        await asyncio.gather(*tasks)

    # Semaphore should have limited concurrent execution
    assert max_active <= concurrency


# ---------------------------------------------------------------------------
# 17. Default concurrency constant is reasonable
# ---------------------------------------------------------------------------
def test_default_concurrency_constant():
    """CONCURRENCY_PER_WORKER should be a reasonable positive integer."""
    assert CONCURRENCY_PER_WORKER >= 1
    assert CONCURRENCY_PER_WORKER <= 50
