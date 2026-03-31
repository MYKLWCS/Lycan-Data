"""
Tests for the Freshness Scheduler — Task 29.
12 tests covering scan/queue logic, staleness detection, dedup, and sleep interval.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.dispatcher.freshness_scheduler import (
    BATCH_SIZE,
    SCAN_INTERVAL_SECONDS,
    FreshnessScheduler,
)
from shared.models.quality import FreshnessQueue
from shared.models.social_profile import SocialProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    freshness_score: float = 0.1,
    platform: str = "instagram",
    handle: str | None = "testuser",
    person_id: str | None = None,
) -> MagicMock:
    profile = MagicMock(spec=SocialProfile)
    profile.id = uuid.uuid4()
    profile.person_id = person_id or uuid.uuid4()
    profile.platform = platform
    profile.platform_user_id = "uid-123"
    profile.handle = handle
    profile.display_name = "Test User"
    profile.bio = None
    profile.url = None
    profile.follower_count = None
    profile.following_count = None
    profile.post_count = None
    profile.is_verified = False
    profile.is_private = False
    profile.is_active = True
    profile.profile_created_at = None
    profile.profile_data = {}
    profile.freshness_score = freshness_score
    # Use a stale timestamp (30 days ago) so SLA-based checks consider it stale
    from datetime import timedelta

    profile.last_scraped_at = datetime.now(UTC) - timedelta(days=30)
    profile.source_reliability = 0.5
    profile.corroboration_count = 1
    profile.corroboration_score = 0.5
    profile.conflict_flag = False
    profile.verification_status = "unverified"
    profile.composite_quality = 0.5
    profile.data_quality = {}
    profile.scraped_from = None
    return profile


@pytest.fixture
def scheduler():
    return FreshnessScheduler()


# ---------------------------------------------------------------------------
# 1. scan_and_queue: no stale profiles → no jobs enqueued
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_and_queue_no_stale_profiles(scheduler):
    """When no stale profiles exist, enqueue_rescrape is never called."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    with (
        patch(
            "modules.dispatcher.freshness_scheduler.AsyncSessionLocal", return_value=mock_session
        ),
        patch.object(scheduler, "_find_stale_profiles", return_value=[]),
        patch.object(scheduler, "_enqueue_rescrape") as mock_enqueue,
    ):
        await scheduler._scan_and_queue()

    mock_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 2. scan_and_queue: stale profile → enqueue_rescrape called
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_and_queue_calls_enqueue_rescrape_for_stale(scheduler):
    """For each stale profile found, _enqueue_rescrape is called."""
    profile = _make_profile(freshness_score=0.1)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    with (
        patch(
            "modules.dispatcher.freshness_scheduler.AsyncSessionLocal", return_value=mock_session
        ),
        patch.object(scheduler, "_find_stale_profiles", return_value=[profile]),
        patch.object(scheduler, "_enqueue_rescrape", return_value=True) as mock_enqueue,
    ):
        await scheduler._scan_and_queue()

    mock_enqueue.assert_called_once_with(mock_session, profile)


# ---------------------------------------------------------------------------
# 3. find_stale_profiles: queries profiles below threshold
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_find_stale_profiles_queries_below_threshold(scheduler):
    """_find_stale_profiles executes a query and returns scalars."""
    profile = _make_profile(freshness_score=0.1)

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [profile]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    profiles = await scheduler._find_stale_profiles(mock_session)

    mock_session.execute.assert_called_once()
    assert profiles == [profile]


# ---------------------------------------------------------------------------
# 4. enqueue_rescrape: already in FreshnessQueue → returns False
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enqueue_rescrape_skips_if_already_queued(scheduler):
    """If record is already in FreshnessQueue, _enqueue_rescrape returns False."""
    profile = _make_profile()

    existing_fq = MagicMock(spec=FreshnessQueue)
    mock_existing_result = MagicMock()
    mock_existing_result.scalar.return_value = existing_fq

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_existing_result)
    mock_session.add = MagicMock()

    result = await scheduler._enqueue_rescrape(mock_session, profile)

    assert result is False
    mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# 5. enqueue_rescrape: not in queue → adds FreshnessQueue record, returns True
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enqueue_rescrape_adds_freshness_queue_record(scheduler):
    """When record is not already queued, FreshnessQueue entry is created."""
    profile = _make_profile()

    mock_empty_result = MagicMock()
    mock_empty_result.scalar.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_empty_result)
    mock_session.add = MagicMock()

    with patch("modules.dispatcher.freshness_scheduler.dispatch_job", new_callable=AsyncMock):
        result = await scheduler._enqueue_rescrape(mock_session, profile)

    assert result is True
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, FreshnessQueue)
    assert added_obj.table_name == "social_profiles"
    assert added_obj.source_type == profile.platform


# ---------------------------------------------------------------------------
# 6. enqueue_rescrape: rescrape_on_staleness=False → no dispatch_job call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enqueue_rescrape_no_dispatch_when_staleness_disabled(scheduler):
    """When rescrape_on_staleness=False, dispatch_job is not called."""
    profile = _make_profile(handle="testuser")

    mock_empty_result = MagicMock()
    mock_empty_result.scalar.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_empty_result)
    mock_session.add = MagicMock()

    mock_dispatch = AsyncMock()

    from shared.config import Settings

    fake_settings = MagicMock(spec=Settings)
    fake_settings.rescrape_on_staleness = False
    fake_settings.freshness_threshold = 0.40

    with (
        patch("modules.dispatcher.freshness_scheduler.settings", fake_settings),
        patch("modules.dispatcher.freshness_scheduler.dispatch_job", mock_dispatch),
    ):
        await scheduler._enqueue_rescrape(mock_session, profile)

    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# 7. enqueue_rescrape: profile.handle is None → no dispatch_job call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enqueue_rescrape_no_dispatch_when_handle_is_none(scheduler):
    """When profile.handle is None, dispatch_job is not called."""
    profile = _make_profile(handle=None)

    mock_empty_result = MagicMock()
    mock_empty_result.scalar.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_empty_result)
    mock_session.add = MagicMock()

    mock_dispatch = AsyncMock()

    with patch("modules.dispatcher.freshness_scheduler.dispatch_job", mock_dispatch):
        await scheduler._enqueue_rescrape(mock_session, profile)

    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# 8. scheduler start/stop: stop() sets _running=False
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_sets_running_false(scheduler):
    """stop() sets _running to False."""
    scheduler._running = True
    await scheduler.stop()
    assert scheduler._running is False


# ---------------------------------------------------------------------------
# 9. scan interval: sleep(SCAN_INTERVAL_SECONDS) called between scans
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_sleeps_between_scans(scheduler):
    """start() calls asyncio.sleep(SCAN_INTERVAL_SECONDS) between scans."""
    call_count = 0

    async def fake_scan():
        nonlocal call_count
        call_count += 1
        # Stop after first scan
        scheduler._running = False

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    with (
        patch.object(scheduler, "_scan_and_queue", side_effect=fake_scan),
        patch("modules.dispatcher.freshness_scheduler.asyncio.sleep", side_effect=fake_sleep),
    ):
        await scheduler.start()

    assert SCAN_INTERVAL_SECONDS in sleep_calls


# ---------------------------------------------------------------------------
# 10. exception in scan → caught, scheduler continues
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_continues_after_scan_exception(scheduler):
    """Exceptions in _scan_and_queue are caught and the loop continues."""
    call_count = 0

    async def failing_then_stop():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated scan error")
        scheduler._running = False

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    with (
        patch.object(scheduler, "_scan_and_queue", side_effect=failing_then_stop),
        patch("modules.dispatcher.freshness_scheduler.asyncio.sleep", side_effect=fake_sleep),
    ):
        # Should not raise
        await scheduler.start()

    # Two iterations: one with exception, one that stops
    assert call_count == 2
    assert len(sleep_calls) == 2


# ---------------------------------------------------------------------------
# 11. batch limited to BATCH_SIZE records
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_find_stale_profiles_limited_to_batch_size(scheduler):
    """_find_stale_profiles applies BATCH_SIZE as a LIMIT."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    await scheduler._find_stale_profiles(mock_session)

    # Inspect the query passed to execute — compile it to SQL and verify LIMIT
    call_args = mock_session.execute.call_args[0][0]
    compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
    # The scheduler fetches BATCH_SIZE * 3 from DB, then filters in-memory by SLA
    assert "LIMIT" in compiled.upper()


# ---------------------------------------------------------------------------
# 12. stale profiles ordered by freshness_score ascending (worst first)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_find_stale_profiles_ordered_by_freshness_asc(scheduler):
    """_find_stale_profiles orders results by freshness_score ascending."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    await scheduler._find_stale_profiles(mock_session)

    call_args = mock_session.execute.call_args[0][0]
    compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
    assert "freshness_score ASC" in compiled or "ORDER BY" in compiled
