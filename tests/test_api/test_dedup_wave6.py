"""
test_dedup_wave6.py — Coverage for api/routes/dedup.py

Targets:
  lines 27-34: get_auto_queue_rows — DB query returning DedupReview rows
  lines 96-98: dedup_auto_merge_run — exception path raises HTTPException 500
"""
from __future__ import annotations

import uuid
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.dedup import router


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/dedup")
    return app


# ---------------------------------------------------------------------------
# Helper — build a fake DedupReview row
# ---------------------------------------------------------------------------


def _fake_review(score: float = 0.91) -> MagicMock:
    r = MagicMock()
    r.id = uuid.uuid4()
    r.person_a_id = uuid.uuid4()
    r.person_b_id = uuid.uuid4()
    r.similarity_score = score
    r.reviewed = False
    r.decision = None
    r.created_at = datetime.now(UTC)
    return r


# ---------------------------------------------------------------------------
# 1. get_auto_queue_rows (lines 27-34)
#    Returns a list of serialized review dicts when rows exist.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_auto_queue_rows_returns_serialized_dicts():
    """Lines 27-34: session.execute → scalars → serialized rows returned."""
    from api.routes.dedup import get_auto_queue_rows

    review = _fake_review(score=0.93)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [review]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    rows = await get_auto_queue_rows(mock_session)

    assert len(rows) == 1
    assert rows[0]["similarity_score"] == 0.93
    assert rows[0]["reviewed"] is False
    assert "id" in rows[0]
    assert "person_a_id" in rows[0]
    assert "person_b_id" in rows[0]


@pytest.mark.asyncio
async def test_get_auto_queue_rows_empty_returns_empty_list():
    """Lines 27-34: no rows → empty list."""
    from api.routes.dedup import get_auto_queue_rows

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    rows = await get_auto_queue_rows(mock_session)
    assert rows == []


# ---------------------------------------------------------------------------
# 2. dedup_auto_merge_run (lines 96-98)
#    When AutoDedupDaemon._run_batch raises, endpoint raises HTTPException 500.
# ---------------------------------------------------------------------------


def test_dedup_auto_merge_run_exception_returns_500():
    """Lines 96-98: _run_batch raises → HTTPException(500) raised."""
    from api.deps import db_session

    app = _make_app()

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())

    async def _override():
        yield mock_session

    app.dependency_overrides[db_session] = _override

    with patch(
        "api.routes.dedup.AutoDedupDaemon._run_batch",
        new=AsyncMock(side_effect=RuntimeError("batch exploded")),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/dedup/auto-merge/run")

    assert response.status_code == 500
    assert "Dedup batch failed" in response.text


def test_dedup_auto_merge_run_success_returns_ok():
    """Happy path: _run_batch succeeds → {status: ok}."""
    from api.deps import db_session

    app = _make_app()

    mock_session = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[db_session] = _override

    with patch(
        "api.routes.dedup.AutoDedupDaemon._run_batch",
        new=AsyncMock(return_value=None),
    ):
        client = TestClient(app)
        response = client.post("/dedup/auto-merge/run")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
