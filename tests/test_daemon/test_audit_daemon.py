"""Tests for AuditDaemon — Task 3 of Phase 6."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.models  # noqa: F401 — force mapper resolution


def test_audit_daemon_importable():
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()
    assert hasattr(daemon, "start")
    assert hasattr(daemon, "_run_audit")


def test_audit_daemon_has_stop():
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()
    assert hasattr(daemon, "stop")


@pytest.mark.asyncio
async def test_daemon_start_stops_cleanly():
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()

    async def _stop_after():
        await asyncio.sleep(0.05)
        daemon.stop()

    with patch.object(daemon, "_run_audit", new_callable=AsyncMock) as mock_run:
        with patch("modules.audit.audit_daemon._SLEEP_SECONDS", 0):
            stopper = asyncio.create_task(_stop_after())
            runner = asyncio.create_task(daemon.start())
            await asyncio.gather(stopper, runner, return_exceptions=True)

    assert mock_run.call_count >= 1


def _make_mock_session(execute_side_effects: list) -> tuple[MagicMock, list]:
    """Return (mock_session, added_objects) with execute side effects wired up."""
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(side_effect=execute_side_effects)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.close = AsyncMock()

    added_objects: list = []
    mock_session.add.side_effect = lambda obj: added_objects.append(obj)
    return mock_session, added_objects


def _scalar(value) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _crawl_result(rows: list) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.all.return_value = rows
    return r


@pytest.mark.asyncio
async def test_run_audit_builds_system_audit_row():
    """_run_audit() should write a SystemAudit row via the session."""
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()

    mock_session, added_objects = _make_mock_session(
        [
            _scalar(200),  # persons_total
            _scalar(30),  # persons_low_coverage
            _scalar(12),  # persons_stale
            _scalar(3),  # persons_conflict
            _scalar(5),  # crawlers_total (data_sources)
            _crawl_result([]),  # crawl health — no jobs in 24h
            _scalar(88),  # tags_assigned_today
            _scalar(7),  # merges_today
            _scalar(15),  # persons_ingested_today
        ]
    )

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("modules.audit.audit_daemon.AsyncSessionLocal", return_value=mock_ctx):
        await daemon._run_audit()

    from shared.models.audit import SystemAudit

    assert len(added_objects) == 1
    row = added_objects[0]
    assert isinstance(row, SystemAudit)
    assert row.persons_total == 200
    assert row.persons_low_coverage == 30
    assert row.persons_stale == 12
    assert row.persons_conflict == 3
    assert row.tags_assigned_today == 88
    assert row.merges_today == 7
    assert row.persons_ingested_today == 15
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_audit_marks_degraded_crawlers():
    """Crawlers with 0 success_rate appear in crawlers_degraded."""
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()

    crawl_rows = [
        {"job_type": "twitter", "found_count": 0, "error_count": 5},
        {"job_type": "linkedin", "found_count": 10, "error_count": 1},
        {"job_type": "empty_crawler", "found_count": 0, "error_count": 0},  # total==0 → skip
    ]

    mock_session, added_objects = _make_mock_session(
        [
            _scalar(10),  # persons_total
            _scalar(1),  # persons_low_coverage
            _scalar(0),  # persons_stale
            _scalar(0),  # persons_conflict
            _scalar(2),  # crawlers_total (data_sources)
            _crawl_result(crawl_rows),  # crawl health
            _scalar(5),  # tags_assigned_today
            _scalar(1),  # merges_today
            _scalar(2),  # persons_ingested_today
        ]
    )

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("modules.audit.audit_daemon.AsyncSessionLocal", return_value=mock_ctx):
        await daemon._run_audit()

    row = added_objects[0]
    assert row.crawlers_total == 2
    assert row.crawlers_healthy == 1
    assert len(row.crawlers_degraded) == 1
    assert row.crawlers_degraded[0]["name"] == "twitter"
    assert row.crawlers_degraded[0]["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_run_audit_handles_db_error_gracefully():
    """If the DB fails, _run_audit should log and not raise."""
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB connection refused"))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("modules.audit.audit_daemon.AsyncSessionLocal", return_value=mock_ctx):
        # Should not raise
        await daemon._run_audit()
