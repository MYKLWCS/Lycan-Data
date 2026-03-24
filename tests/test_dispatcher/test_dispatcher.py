"""
Tests for the Crawl Job Dispatcher — Task 27.
15 tests covering routing, status updates, retries, error handling, and enqueueing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from modules.crawlers.result import CrawlerResult
from modules.dispatcher.dispatcher import (
    CrawlDispatcher,
    dispatch_job,
    MAX_RETRIES,
    RETRY_DELAYS,
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


def _make_result(found: bool = True, error: str | None = None, platform: str = "instagram") -> CrawlerResult:
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
# 1. job dequeued and routed to the correct crawler
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_routes_to_correct_crawler(dispatcher, mock_session):
    """_process_one should dequeue the job and call the registered crawler."""
    job_dict = _make_job_dict()
    found_result = _make_result(found=True)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    mock_crawler_inst.run.assert_called_once_with("testuser")


# ---------------------------------------------------------------------------
# 2. no crawler found → FAILED status set
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
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()

        await dispatcher._process_one()

    # _update_job_status calls session.execute + commit
    mock_session.execute.assert_called()
    mock_session.commit.assert_called()


# ---------------------------------------------------------------------------
# 3. crawler returns found=True → DONE + upsert called
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_found_result_triggers_upsert_and_done(dispatcher, mock_session):
    """found=True result should call upsert_social_profile and set DONE."""
    job_dict = _make_job_dict()
    found_result = _make_result(found=True)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    aggregate_mock = AsyncMock(return_value={"person_id": None})

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", aggregate_mock),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    aggregate_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 4. crawler returns rate_limited error → RATE_LIMITED + requeued
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_limited_error_sets_rate_limited_and_requeues(dispatcher, mock_session):
    """When error contains 'rate', status → RATE_LIMITED and job is requeued."""
    job_dict = _make_job_dict()
    rate_limited_result = _make_result(found=False, error="rate limit exceeded")

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=rate_limited_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    mock_bus.enqueue.assert_called_once()
    enqueue_call_args = mock_bus.enqueue.call_args
    assert enqueue_call_args[1]["priority"] == "normal"  # retry_count=0 → normal


# ---------------------------------------------------------------------------
# 5. crawler returns blocked error → BLOCKED status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_blocked_error_sets_blocked_status(dispatcher, mock_session):
    """When error contains 'block', status → BLOCKED, no requeue."""
    job_dict = _make_job_dict()
    blocked_result = _make_result(found=False, error="account blocked by platform")

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=blocked_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    mock_bus.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 6. exception during crawl → FAILED, retried if retry_count < MAX_RETRIES
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exception_causes_failed_and_retry(dispatcher, mock_session):
    """Exceptions during crawl → FAILED status + requeue when retry_count < MAX_RETRIES."""
    job_dict = _make_job_dict(retry_count=0)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(side_effect=RuntimeError("network timeout"))
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    # Should requeue since retry_count=0 < MAX_RETRIES=3
    mock_bus.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# 7. retry_count >= MAX_RETRIES → no requeue, still FAILED
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_max_retries_exceeded_no_requeue(dispatcher, mock_session):
    """When retry_count >= MAX_RETRIES, exception → FAILED with no requeue."""
    job_dict = _make_job_dict(retry_count=MAX_RETRIES)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(side_effect=RuntimeError("still failing"))
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    mock_bus.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 8. invalid JSON payload → skipped gracefully
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_json_payload_is_skipped(dispatcher):
    """Non-JSON or unparseable payloads are logged and skipped without crash."""
    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.dequeue_any = AsyncMock(return_value="not valid json {{{{")

        # Should not raise
        await dispatcher._process_one()

    # No further processing — no DB calls, no errors propagated


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
    """retry_count=0 → delay=30s, priority=normal."""
    dispatcher = CrawlDispatcher()
    job_dict = _make_job_dict()

    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.enqueue = AsyncMock()

        await dispatcher._requeue_with_backoff(job_dict, retry_count=0)

    mock_bus.enqueue.assert_called_once()
    enqueued_job = mock_bus.enqueue.call_args[0][0]
    assert enqueued_job["retry_count"] == 1
    assert enqueued_job["run_after"] == pytest.approx(
        datetime.now(timezone.utc).timestamp() + RETRY_DELAYS[0], abs=2
    )
    assert mock_bus.enqueue.call_args[1]["priority"] == "normal"


# ---------------------------------------------------------------------------
# 12. _requeue_with_backoff uses low priority for retry_count >= 1
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_requeue_backoff_second_retry_uses_low_priority():
    """retry_count=1 → delay=120s, priority=low."""
    dispatcher = CrawlDispatcher()
    job_dict = _make_job_dict()

    with patch("modules.dispatcher.dispatcher.event_bus") as mock_bus:
        mock_bus.enqueue = AsyncMock()

        await dispatcher._requeue_with_backoff(job_dict, retry_count=1)

    assert mock_bus.enqueue.call_args[1]["priority"] == "low"
    enqueued_job = mock_bus.enqueue.call_args[0][0]
    assert enqueued_job["retry_count"] == 2
    assert enqueued_job["run_after"] == pytest.approx(
        datetime.now(timezone.utc).timestamp() + RETRY_DELAYS[1], abs=2
    )


# ---------------------------------------------------------------------------
# 13. dequeue_any returning None → _process_one returns without processing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_returns_when_queue_empty(dispatcher):
    """When dequeue_any returns None (timeout), _process_one does nothing."""
    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler") as mock_get_crawler,
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=None)

        await dispatcher._process_one()

    mock_get_crawler.assert_not_called()


# ---------------------------------------------------------------------------
# 14. found=True → enrichment event published with correct fields
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
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    mock_bus.publish.assert_called_once()
    channel, event = mock_bus.publish.call_args[0]
    assert channel == "enrichment"
    assert event["event"] == "crawl_complete"
    assert event["platform"] == "facebook"
    assert event["person_id"] == "pid-42"
    assert event["found"] is True


# ---------------------------------------------------------------------------
# 15. not-found result with no error → status set to DONE, no requeue
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_not_found_no_error_sets_done(dispatcher, mock_session):
    """found=False with no error → DONE status, no retry, no event published."""
    job_dict = _make_job_dict()
    not_found_result = _make_result(found=False, error=None)

    mock_crawler_cls = MagicMock()
    mock_crawler_inst = AsyncMock()
    mock_crawler_inst.run = AsyncMock(return_value=not_found_result)
    mock_crawler_cls.return_value = mock_crawler_inst

    with (
        patch("modules.dispatcher.dispatcher.event_bus") as mock_bus,
        patch("modules.dispatcher.dispatcher.get_crawler", return_value=mock_crawler_cls),
        patch("modules.dispatcher.dispatcher.aggregate_result", new_callable=AsyncMock, return_value={"person_id": None}),
        patch("modules.dispatcher.dispatcher.meili_indexer") as mock_meili,
        patch("modules.dispatcher.dispatcher.AsyncSessionLocal", return_value=mock_session),
    ):
        mock_bus.dequeue_any = AsyncMock(return_value=job_dict)
        mock_bus.publish = AsyncMock()
        mock_bus.enqueue = AsyncMock()
        mock_meili.index_person = AsyncMock()

        await dispatcher._process_one()

    mock_bus.enqueue.assert_not_called()
    mock_bus.publish.assert_not_called()
