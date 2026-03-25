"""Tests for new auto-dedup API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app


def _make_session():
    session = AsyncMock()
    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
        mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
    )
    session.execute = AsyncMock(return_value=default_exec)
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def test_get_auto_queue_returns_list():
    """GET /dedup/auto-queue returns pending DedupReview rows."""
    session = _make_session()

    async def _override():
        yield session

    app.dependency_overrides[db_session] = _override

    with patch(
        "api.routes.dedup.get_auto_queue_rows",
        new=AsyncMock(
            return_value=[
                {
                    "id": str(uuid.uuid4()),
                    "person_a_id": str(uuid.uuid4()),
                    "person_b_id": str(uuid.uuid4()),
                    "similarity_score": 0.77,
                    "reviewed": False,
                    "decision": None,
                }
            ]
        ),
    ):
        with TestClient(app) as client:
            resp = client.get("/dedup/auto-queue")
            assert resp.status_code == 200
            body = resp.json()
            assert "reviews" in body
            assert "count" in body

    app.dependency_overrides.clear()


def test_post_auto_merge_run_triggers_batch():
    """POST /dedup/auto-merge/run triggers one immediate batch."""
    session = _make_session()

    async def _override():
        yield session

    app.dependency_overrides[db_session] = _override

    with patch("api.routes.dedup.AutoDedupDaemon") as MockDaemon:
        instance = AsyncMock()
        instance._run_batch = AsyncMock(return_value=None)
        MockDaemon.return_value = instance

        with TestClient(app) as client:
            resp = client.post("/dedup/auto-merge/run")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("status") == "ok"

    app.dependency_overrides.clear()
