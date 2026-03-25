"""
Family tree API endpoint tests — no live DB required.

Tests:
  GET  /persons/{id}/family-tree         → not_built when no snapshot
  POST /persons/{id}/family-tree/build   → queued
  GET  /persons/{id}/family-tree/status  → not_started
  GET  /persons/{id}/relatives           → empty list for new person
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app

# ── Mock session builder ───────────────────────────────────────────────────────


def _make_session(get_return=None):
    session = AsyncMock()

    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
    )
    session.execute.return_value = default_exec
    session.get.return_value = get_return
    session.commit = AsyncMock()
    return session


def _override_db(session):
    async def _dep():
        yield session

    return _dep


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


TEST_ID = str(uuid.uuid4())


# ── GET /persons/{id}/family-tree ──────────────────────────────────────────────


def test_get_family_tree_not_built():
    """Returns not_built when no snapshot exists."""
    session = _make_session()
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/family-tree")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_built"
    assert "build" in data["message"]


# ── POST /persons/{id}/family-tree/build ──────────────────────────────────────


def test_build_family_tree_queued():
    """Returns queued when person exists."""
    mock_person = MagicMock()
    mock_person.meta = {}
    mock_person.id = uuid.UUID(TEST_ID)

    session = _make_session(get_return=mock_person)
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.post(f"/persons/{TEST_ID}/family-tree/build")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["person_id"] == TEST_ID


def test_build_family_tree_person_not_found():
    """Returns 404 when person does not exist."""
    session = _make_session(get_return=None)
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.post(f"/persons/{TEST_ID}/family-tree/build")

    assert resp.status_code == 404


# ── GET /persons/{id}/family-tree/status ──────────────────────────────────────


def test_family_tree_status_not_started():
    """Returns not_started when no snapshot exists."""
    session = _make_session()
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/family-tree/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_started"


# ── GET /persons/{id}/relatives ───────────────────────────────────────────────


def test_list_relatives_empty():
    """Returns empty list for a person with no relationships."""
    session = _make_session()
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/relatives")

    assert resp.status_code == 200
    data = resp.json()
    assert data["person_id"] == TEST_ID
    assert data["relatives"] == []
    assert data["count"] == 0


# ── Invalid UUID ───────────────────────────────────────────────────────────────


def test_get_family_tree_invalid_uuid():
    session = _make_session()
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get("/persons/not-a-uuid/family-tree")

    assert resp.status_code == 400
