"""
Tests for modules/pipeline/ingestion_daemon.py

Covers:
- IngestionDaemon initialises with correct defaults
- stop() sets _running to False
- _process_one returns early when queue is empty
- _process_one handles invalid JSON gracefully
- _process_one processes a valid dict payload end-to-end
- _process_one handles a plain JSON string payload
- aggregate_result errors are caught and session is rolled back
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.pipeline.ingestion_daemon import IngestionDaemon

# ---------------------------------------------------------------------------
# Helper: build a minimal valid ingest payload
# ---------------------------------------------------------------------------


def _make_payload(found: bool = True, platform: str = "instagram") -> dict:
    return {
        "platform": platform,
        "identifier": "testuser",
        "found": found,
        "data": {"handle": "testuser", "bio": "hello"} if found else {},
        "person_id": "00000000-0000-0000-0000-000000000001",
        "result": {},
        "source_reliability": 0.7,
    }


# ---------------------------------------------------------------------------
# 1. Default initialisation
# ---------------------------------------------------------------------------
def test_daemon_default_init():
    daemon = IngestionDaemon()
    assert daemon.worker_id == "ingester-1"
    assert daemon._running is False


def test_daemon_custom_worker_id():
    daemon = IngestionDaemon(worker_id="worker-99")
    assert daemon.worker_id == "worker-99"


# ---------------------------------------------------------------------------
# 2. stop() sets _running to False
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_sets_running_false():
    daemon = IngestionDaemon()
    daemon._running = True
    await daemon.stop()
    assert daemon._running is False


# ---------------------------------------------------------------------------
# 3. _process_one returns immediately when queue is empty
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_returns_early_on_empty_queue():
    daemon = IngestionDaemon()

    with patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus:
        mock_bus.dequeue = AsyncMock(return_value=None)
        # Should not raise, should return immediately
        await daemon._process_one()
        mock_bus.dequeue.assert_awaited_once_with(priority="ingest", timeout=5)


# ---------------------------------------------------------------------------
# 4. _process_one logs warning and returns on invalid JSON string
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_handles_invalid_json():
    daemon = IngestionDaemon()

    with patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus:
        mock_bus.dequeue = AsyncMock(return_value="not-valid-json{{{")
        # Should not raise
        await daemon._process_one()


# ---------------------------------------------------------------------------
# 5. _process_one processes a valid dict payload successfully
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_valid_dict_payload():
    daemon = IngestionDaemon()
    payload = _make_payload(found=True)
    pid = payload["person_id"]

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.rollback = AsyncMock()

    with (
        patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus,
        patch("modules.pipeline.ingestion_daemon.AsyncSessionLocal", return_value=mock_session),
        patch(
            "modules.pipeline.ingestion_daemon.aggregate_result",
            new=AsyncMock(return_value={"person_id": pid, "written": True}),
        ),
        patch("modules.pipeline.ingestion_daemon.pivot_from_result", new=AsyncMock(return_value=0)),
        patch("modules.pipeline.ingestion_daemon._orchestrator") as mock_orch,
    ):
        mock_bus.dequeue = AsyncMock(return_value=payload)
        mock_bus.enqueue = AsyncMock()
        mock_orch.enrich_person = AsyncMock()

        await daemon._process_one()

    # Should have enqueued the person to the index queue
    mock_bus.enqueue.assert_awaited_once_with({"person_id": pid}, priority="index")


# ---------------------------------------------------------------------------
# 6. _process_one handles a raw JSON string payload
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_json_string_payload():
    daemon = IngestionDaemon()
    payload = _make_payload(found=False)
    raw = json.dumps(payload)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.rollback = AsyncMock()

    with (
        patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus,
        patch("modules.pipeline.ingestion_daemon.AsyncSessionLocal", return_value=mock_session),
        patch(
            "modules.pipeline.ingestion_daemon.aggregate_result",
            new=AsyncMock(return_value={"written": False, "reason": "no data"}),
        ),
        patch("modules.pipeline.ingestion_daemon.pivot_from_result", new=AsyncMock(return_value=0)),
        patch("modules.pipeline.ingestion_daemon._orchestrator"),
    ):
        mock_bus.dequeue = AsyncMock(return_value=raw)
        mock_bus.enqueue = AsyncMock()

        # Should not raise
        await daemon._process_one()


# ---------------------------------------------------------------------------
# 7. aggregate_result exceptions roll back the session
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_one_aggregate_error_triggers_rollback():
    daemon = IngestionDaemon()
    payload = _make_payload(found=True)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.rollback = AsyncMock()

    with (
        patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus,
        patch("modules.pipeline.ingestion_daemon.AsyncSessionLocal", return_value=mock_session),
        patch(
            "modules.pipeline.ingestion_daemon.aggregate_result",
            new=AsyncMock(side_effect=RuntimeError("DB down")),
        ),
        patch("modules.pipeline.ingestion_daemon._orchestrator"),
    ):
        mock_bus.dequeue = AsyncMock(return_value=payload)
        mock_bus.enqueue = AsyncMock()

        # Should not propagate — daemon catches errors internally
        await daemon._process_one()

    mock_session.rollback.assert_awaited_once()
