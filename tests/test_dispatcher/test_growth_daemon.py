"""
Tests for the Growth Daemon — Task 28.
12 tests covering event handling, fan-out logic, kill switches, dedup, and priority.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.dispatcher.growth_daemon import (
    COOLDOWN_SECONDS,
    KILL_SWITCHES,
    MAX_DAILY_GROWTH_JOBS,
    MAX_DEPTH,
    MAX_FANOUT_PER_PERSON,
    PLATFORM_ACCEPTS,
    GrowthDaemon,
)
from shared.models.identifier import Identifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_identifier(type_: str, value: str, person_id: str | None = None) -> MagicMock:
    ident = MagicMock(spec=Identifier)
    ident.id = uuid.uuid4()
    ident.type = type_
    ident.value = value
    ident.person_id = person_id or str(uuid.uuid4())
    ident.normalized_value = None
    ident.country_code = None
    ident.confidence = 1.0
    ident.is_primary = False
    ident.meta = {}
    return ident


def _make_event(**kwargs) -> dict:
    base = {
        "event": "crawl_complete",
        "person_id": "person-123",
        "depth": 0,
    }
    base.update(kwargs)
    return base


@pytest.fixture
def daemon():
    return GrowthDaemon()


# ---------------------------------------------------------------------------
# 1. non-crawl_complete event → ignored
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_event_ignores_non_crawl_complete(daemon):
    """Events with event != 'crawl_complete' are silently dropped."""
    with patch.object(daemon, "_get_person_identifiers") as mock_get:
        await daemon._handle_event({"event": "some_other_event", "person_id": "p1"})
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 2. no person_id → ignored
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_event_ignores_missing_person_id(daemon):
    """Events with no person_id are silently dropped."""
    with patch.object(daemon, "_get_person_identifiers") as mock_get:
        await daemon._handle_event({"event": "crawl_complete"})
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 3. depth >= MAX_DEPTH → no fan-out
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_event_stops_at_max_depth(daemon):
    """When depth >= MAX_DEPTH, fan-out is skipped entirely."""
    msg = _make_event(depth=MAX_DEPTH)

    with (
        patch("modules.dispatcher.growth_daemon.AsyncSessionLocal") as mock_session_cls,
        patch.object(daemon, "_fan_out") as mock_fan_out,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        await daemon._handle_event(msg)

    mock_fan_out.assert_not_called()


# ---------------------------------------------------------------------------
# 4. phone identifier → enqueues phone_carrier, phone_fonefinder, phone_truecaller,
#    whatsapp, telegram
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_phone_enqueues_phone_platforms(daemon):
    """A phone-type identifier fans out to all phone-accepting platforms."""
    phone_ident = _make_identifier("phone", "+15550001234", "person-abc")
    person_id = "person-abc"
    depth = 0

    dispatched_platforms = []

    async def fake_dispatch(platform, identifier, person_id, priority):
        dispatched_platforms.append(platform)

    with (
        patch("modules.dispatcher.growth_daemon.dispatch_job", side_effect=fake_dispatch),
        patch.object(daemon, "_job_exists", return_value=False),
    ):
        await daemon._fan_out(phone_ident, person_id, depth, MAX_FANOUT_PER_PERSON)

    phone_platforms = {p for p, types in PLATFORM_ACCEPTS.items() if "phone" in types}
    for platform in phone_platforms:
        # Check kill switch status — only verify platforms that are not killed by default
        switch = KILL_SWITCHES.get(platform)
        if switch is None:
            assert platform in dispatched_platforms, f"Expected {platform} in dispatched"

    # Specifically verify the well-known phone platforms
    for expected in [
        "phone_carrier",
        "phone_fonefinder",
        "phone_truecaller",
        "whatsapp",
        "telegram",
    ]:
        assert expected in dispatched_platforms, f"Missing expected platform: {expected}"


# ---------------------------------------------------------------------------
# 5. email identifier → enqueues email_holehe, email_hibp
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_email_enqueues_email_platforms(daemon):
    """An email-type identifier fans out to email_holehe and email_hibp."""
    email_ident = _make_identifier("email", "test@example.com", "person-abc")
    person_id = "person-abc"
    depth = 0

    dispatched_platforms = []

    async def fake_dispatch(platform, identifier, person_id, priority):
        dispatched_platforms.append(platform)

    with (
        patch("modules.dispatcher.growth_daemon.dispatch_job", side_effect=fake_dispatch),
        patch.object(daemon, "_job_exists", return_value=False),
    ):
        await daemon._fan_out(email_ident, person_id, depth, MAX_FANOUT_PER_PERSON)

    assert "email_holehe" in dispatched_platforms
    assert "email_hibp" in dispatched_platforms


# ---------------------------------------------------------------------------
# 6. username identifier → enqueues instagram, twitter, snapchat, github, etc.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_username_enqueues_username_platforms(daemon):
    """A username-type identifier fans out to all username-accepting platforms."""
    username_ident = _make_identifier("username", "johndoe", "person-abc")
    person_id = "person-abc"
    depth = 0

    dispatched_platforms = []

    async def fake_dispatch(platform, identifier, person_id, priority):
        dispatched_platforms.append(platform)

    with (
        patch("modules.dispatcher.growth_daemon.dispatch_job", side_effect=fake_dispatch),
        patch.object(daemon, "_job_exists", return_value=False),
    ):
        await daemon._fan_out(username_ident, person_id, depth, MAX_FANOUT_PER_PERSON)

    for expected in ["instagram", "twitter", "snapchat", "github"]:
        assert expected in dispatched_platforms, f"Missing expected platform: {expected}"


# ---------------------------------------------------------------------------
# 7. kill switch disabled → platform skipped
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_kill_switch_disables_platform(daemon):
    """When a kill switch is disabled, the corresponding platform is not enqueued."""
    username_ident = _make_identifier("username", "johndoe", "person-abc")
    person_id = "person-abc"
    depth = 0

    dispatched_platforms = []

    async def fake_dispatch(platform, identifier, person_id, priority):
        dispatched_platforms.append(platform)

    # Disable instagram via kill switch
    from shared.config import Settings

    fake_settings = MagicMock(spec=Settings)
    fake_settings.enable_instagram = False
    fake_settings.enable_twitter = True
    fake_settings.enable_facebook = True
    fake_settings.enable_tiktok = True
    fake_settings.enable_linkedin = True
    fake_settings.enable_telegram = True
    fake_settings.enable_burner_check = True
    fake_settings.enable_credit_risk = True
    fake_settings.enable_crypto_trace = True
    fake_settings.enable_darkweb = True

    with (
        patch("modules.dispatcher.growth_daemon.settings", fake_settings),
        patch("modules.dispatcher.growth_daemon.dispatch_job", side_effect=fake_dispatch),
        patch.object(daemon, "_job_exists", return_value=False),
    ):
        await daemon._fan_out(username_ident, person_id, depth, MAX_FANOUT_PER_PERSON)

    assert "instagram" not in dispatched_platforms
    # twitter should still be dispatched
    assert "twitter" in dispatched_platforms


# ---------------------------------------------------------------------------
# 8. job_exists returns True → platform skipped (dedup)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_deduplicates_existing_jobs(daemon):
    """When _job_exists returns True, dispatch_job is not called for that platform."""
    email_ident = _make_identifier("email", "test@example.com", "person-abc")
    person_id = "person-abc"
    depth = 0

    mock_dispatch = AsyncMock()

    with (
        patch("modules.dispatcher.growth_daemon.dispatch_job", mock_dispatch),
        patch.object(daemon, "_job_exists", return_value=True),
    ):
        await daemon._fan_out(email_ident, person_id, depth, MAX_FANOUT_PER_PERSON)

    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# 9. job_exists: found non-failed job → True
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_job_exists_returns_true_when_active_job_found(daemon):
    """_job_exists returns True when a non-failed CrawlJob is found."""
    from shared.models.crawl import CrawlJob

    mock_job = MagicMock(spec=CrawlJob)

    mock_result = MagicMock()
    mock_result.scalar.return_value = mock_job

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("modules.dispatcher.growth_daemon.AsyncSessionLocal", return_value=mock_session):
        result = await daemon._job_exists("person-1", "instagram", "testuser")

    assert result is True


# ---------------------------------------------------------------------------
# 10. job_exists: no job found → False
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_job_exists_returns_false_when_no_job(daemon):
    """_job_exists returns False when no CrawlJob matches."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = None

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("modules.dispatcher.growth_daemon.AsyncSessionLocal", return_value=mock_session):
        result = await daemon._job_exists("person-1", "instagram", "testuser")

    assert result is False


# ---------------------------------------------------------------------------
# 11. priority mapping: depth=0 → "high", depth=1 → "normal", depth=2 → "low"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_priority_varies_by_depth(daemon):
    """Priority is high/normal/low based on depth 0/1/2."""
    email_ident = _make_identifier("email", "test@example.com", "person-abc")
    person_id = "person-abc"

    for depth, expected_priority in [(0, "high"), (1, "normal"), (2, "low")]:
        dispatched_priorities = []

        async def fake_dispatch(platform, identifier, person_id, priority, _d=depth):
            dispatched_priorities.append(priority)

        with (
            patch("modules.dispatcher.growth_daemon.dispatch_job", side_effect=fake_dispatch),
            patch.object(daemon, "_job_exists", return_value=False),
        ):
            await daemon._fan_out(email_ident, person_id, depth, MAX_FANOUT_PER_PERSON)

        assert all(p == expected_priority for p in dispatched_priorities), (
            f"Expected all priorities={expected_priority!r} at depth={depth}, got {dispatched_priorities}"
        )


# ---------------------------------------------------------------------------
# 12. PLATFORM_ACCEPTS: phone type maps to correct platforms
# ---------------------------------------------------------------------------
def test_platform_accepts_phone_maps_correctly():
    """PLATFORM_ACCEPTS correctly maps phone-accepting platforms."""
    phone_platforms = {p for p, types in PLATFORM_ACCEPTS.items() if "phone" in types}
    expected = {"telegram", "whatsapp", "phone_carrier", "phone_fonefinder", "phone_truecaller"}
    assert expected == phone_platforms


# ---------------------------------------------------------------------------
# 13. fanout budget caps dispatched jobs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fan_out_respects_budget():
    """_fan_out stops dispatching once remaining_budget is exhausted."""
    username_ident = _make_identifier("username", "johndoe", "person-abc")
    person_id = "person-abc"
    depth = 0
    budget = 2  # only allow 2 jobs

    dispatched_platforms = []

    async def fake_dispatch(platform, identifier, person_id, priority):
        dispatched_platforms.append(platform)

    daemon = GrowthDaemon()
    with (
        patch("modules.dispatcher.growth_daemon.dispatch_job", side_effect=fake_dispatch),
        patch.object(daemon, "_job_exists", return_value=False),
    ):
        count = await daemon._fan_out(username_ident, person_id, depth, budget)

    assert count <= budget
    assert len(dispatched_platforms) <= budget


# ---------------------------------------------------------------------------
# 14. daily cap prevents further job dispatch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_daily_cap_prevents_dispatch():
    """When daily job count hits MAX_DAILY_GROWTH_JOBS, events are dropped."""
    daemon = GrowthDaemon()
    daemon._daily_job_count = MAX_DAILY_GROWTH_JOBS  # already at cap
    daemon._day_marker = int(__import__("time").time()) // 86400  # today

    msg = _make_event(depth=0)

    with patch.object(daemon, "_get_person_identifiers") as mock_get:
        await daemon._handle_event(msg)

    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 15. per-person cooldown prevents rapid re-processing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_per_person_cooldown():
    """Same person_id cannot trigger fan-out within COOLDOWN_SECONDS."""
    import time

    daemon = GrowthDaemon()
    daemon._recent_persons["person-123"] = time.time()  # just processed

    msg = _make_event(depth=0, person_id="person-123")

    with patch.object(daemon, "_get_person_identifiers") as mock_get:
        await daemon._handle_event(msg)

    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 16. volume constants are reasonable
# ---------------------------------------------------------------------------
def test_volume_constants():
    """Volume cap constants are set to reasonable values."""
    assert MAX_FANOUT_PER_PERSON >= 1
    assert MAX_FANOUT_PER_PERSON <= 100
    assert MAX_DAILY_GROWTH_JOBS >= 100
    assert MAX_DAILY_GROWTH_JOBS <= 100000
    assert COOLDOWN_SECONDS >= 1
