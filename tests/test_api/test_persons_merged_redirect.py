"""Tests for HTTP 301 redirect when accessing a merged person record."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app


def _make_session():
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        )
    )
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    return session


def test_merged_person_returns_301():
    """GET /persons/{id} returns 301 with Location header when person is merged."""
    merged_id = uuid.uuid4()
    canonical_id = uuid.uuid4()

    mock_person = MagicMock()
    mock_person.id = merged_id
    mock_person.merged_into = canonical_id

    session = _make_session()
    session.get = AsyncMock(return_value=mock_person)

    async def _override():
        yield session

    app.dependency_overrides[db_session] = _override

    with TestClient(app, follow_redirects=False) as client:
        resp = client.get(f"/persons/{merged_id}")
        assert resp.status_code == 301
        assert str(canonical_id) in resp.headers.get("location", "")

    app.dependency_overrides.clear()


def test_active_person_returns_non_301():
    """GET /persons/{id} does not return 301 for a non-merged person."""
    active_id = uuid.uuid4()

    session = _make_session()
    # session.get returns None → 404 (not 301) — confirms redirect logic doesn't fire
    session.get = AsyncMock(return_value=None)

    async def _override():
        yield session

    app.dependency_overrides[db_session] = _override

    with TestClient(app, follow_redirects=False) as client:
        resp = client.get(f"/persons/{active_id}")
        assert resp.status_code != 301

    app.dependency_overrides.clear()
