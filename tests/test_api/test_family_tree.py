"""
Family tree API endpoint tests — no live DB required.

Tests:
  GET  /persons/{id}/family-tree         → not_built when no snapshot
  GET  /persons/{id}/family-tree         → snapshot found
  POST /persons/{id}/family-tree/build   → queued
  GET  /persons/{id}/family-tree/status  → not_started
  GET  /persons/{id}/family-tree/status  → complete
  GET  /persons/{id}/family-tree/gedcom  → 404 when no snapshot
  GET  /persons/{id}/family-tree/gedcom  → GEDCOM content when snapshot exists
  GET  /persons/{id}/relatives           → empty list for new person
  GET  /persons/{id}/relatives           → list with actual relatives
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── GET /persons/{id}/family-tree — snapshot found ────────────────────────────


def test_get_family_tree_with_snapshot():
    """Returns tree data when snapshot exists (line 985+)."""
    snapshot = MagicMock()
    snapshot.root_person_id = uuid.UUID(TEST_ID)
    snapshot.tree_json = {"nodes": [], "edges": []}
    snapshot.depth_ancestors = 4
    snapshot.depth_descendants = 3
    snapshot.source_count = 12
    snapshot.built_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    snapshot.is_stale = False

    session = _make_session()
    exec_result = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=snapshot),
    )
    session.execute.return_value = exec_result
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/family-tree")

    assert resp.status_code == 200
    data = resp.json()
    assert data["root_person_id"] == TEST_ID
    assert data["depth_ancestors"] == 4
    assert data["is_stale"] is False


# ── GET /persons/{id}/family-tree/status — complete ───────────────────────────


def test_family_tree_status_complete():
    """Returns complete status when snapshot is not stale (line 1026)."""
    snapshot = MagicMock()
    snapshot.is_stale = False
    snapshot.built_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    snapshot.source_count = 5

    session = _make_session()
    exec_result = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=snapshot),
    )
    session.execute.return_value = exec_result
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/family-tree/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "complete"
    assert data["source_count"] == 5


def test_family_tree_status_stale():
    """Returns stale status when snapshot.is_stale is True."""
    snapshot = MagicMock()
    snapshot.is_stale = True
    snapshot.built_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    snapshot.source_count = 3

    session = _make_session()
    exec_result = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=snapshot),
    )
    session.execute.return_value = exec_result
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/family-tree/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "stale"


# ── GET /persons/{id}/family-tree/gedcom ──────────────────────────────────────


def test_get_family_tree_gedcom_404_when_no_snapshot():
    """Returns 404 when no snapshot exists."""
    mock_person = MagicMock()
    mock_person.id = uuid.UUID(TEST_ID)
    mock_person.full_name = "Alice Smith"

    session = _make_session(get_return=mock_person)
    # execute returns None for snapshot
    exec_result = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
    )
    session.execute.return_value = exec_result
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/family-tree/gedcom")

    assert resp.status_code == 404


def test_get_family_tree_gedcom_returns_content():
    """Returns GEDCOM content when snapshot exists (lines 1036-1082)."""
    mock_person = MagicMock()
    mock_person.id = uuid.UUID(TEST_ID)
    mock_person.full_name = "Alice Smith"
    mock_person.date_of_birth = None
    mock_person.gender = None

    snapshot = MagicMock()
    snapshot.root_person_id = uuid.UUID(TEST_ID)
    snapshot.tree_json = {"nodes": [TEST_ID]}

    session = _make_session(get_return=mock_person)

    call_count = [0]

    async def _execute_side_effect(stmt):
        call_count[0] += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = snapshot if call_count[0] == 1 else None
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=_execute_side_effect)
    app.dependency_overrides[db_session] = _override_db(session)

    with patch("modules.export.gedcom.export_gedcom", return_value="0 HEAD\n1 GEDC\n0 TRLR"):
        with TestClient(app) as client:
            resp = client.get(f"/persons/{TEST_ID}/family-tree/gedcom")

    assert resp.status_code == 200


def test_get_family_tree_gedcom_skips_invalid_uuid_nodes():
    """Lines 1069-1070: invalid UUID in tree_json nodes is silently skipped."""
    mock_person = MagicMock()
    mock_person.id = uuid.UUID(TEST_ID)
    mock_person.full_name = "Alice Smith"
    mock_person.date_of_birth = None
    mock_person.gender = None

    snapshot = MagicMock()
    snapshot.root_person_id = uuid.UUID(TEST_ID)
    # Include a valid UUID and an invalid one to hit the except branch
    snapshot.tree_json = {"nodes": ["not-a-valid-uuid", TEST_ID]}

    session = _make_session(get_return=mock_person)

    call_count = [0]

    async def _execute_side_effect(stmt):
        call_count[0] += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = snapshot if call_count[0] == 1 else None
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=_execute_side_effect)
    app.dependency_overrides[db_session] = _override_db(session)

    with patch("modules.export.gedcom.export_gedcom", return_value="0 HEAD\n0 TRLR"):
        with TestClient(app) as client:
            resp = client.get(f"/persons/{TEST_ID}/family-tree/gedcom")

    # Should still return 200 — invalid UUID is swallowed, not propagated
    assert resp.status_code == 200


# ── GET /persons/{id}/relatives — with relationships ──────────────────────────


def test_list_relatives_with_data():
    """Returns relatives when relationships exist (lines 1095-1113)."""
    other_id = uuid.uuid4()
    mock_other_person = MagicMock()
    mock_other_person.full_name = "Bob Smith"

    rel = MagicMock()
    rel.person_b_id = other_id
    rel.rel_type = "sibling"
    rel.score = 0.9

    session = _make_session(get_return=mock_other_person)
    exec_result = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[rel]))),
        scalar_one_or_none=MagicMock(return_value=None),
    )
    session.execute.return_value = exec_result
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get(f"/persons/{TEST_ID}/relatives")

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["relatives"][0]["relationship_type"] == "sibling"
    assert data["relatives"][0]["full_name"] == "Bob Smith"


# ── Invalid UUID ───────────────────────────────────────────────────────────────


def test_get_family_tree_invalid_uuid():
    session = _make_session()
    app.dependency_overrides[db_session] = _override_db(session)

    with TestClient(app) as client:
        resp = client.get("/persons/not-a-uuid/family-tree")

    assert resp.status_code == 400
