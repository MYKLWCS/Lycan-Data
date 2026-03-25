"""API tests for family tree endpoints."""
from __future__ import annotations
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from starlette.testclient import TestClient
from api.deps import db_session
from api.main import app

def _make_person(pid=None, name="Test Person"):
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.full_name = name
    p.date_of_birth = None
    p.meta = {}
    p.merged_into = None
    return p

def _make_snapshot(root_id, built=True, stale=False):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.root_person_id = root_id
    s.tree_json = {"root_person_id": str(root_id), "nodes": {str(root_id): {"id": str(root_id), "name": "Test Person", "birth_date": None, "is_root": True}}, "edges": [], "node_count": 1, "edge_count": 0}
    s.depth_ancestors = 2
    s.depth_descendants = 1
    s.source_count = 3
    s.built_at = datetime.now(UTC)
    s.is_stale = stale
    return s

def _make_result(items):
    r = MagicMock()
    r.scalars.return_value.first.return_value = items[0] if items else None
    r.scalars.return_value.all.return_value = items
    r.scalar_one.return_value = len(items)
    r.scalar_one_or_none.return_value = items[0] if items else None
    return r

def _make_session(person=None, snapshot=None, relatives=None):
    session = AsyncMock()
    async def _get(model, pk): return person
    session.get = AsyncMock(side_effect=_get)
    results_queue = []
    if snapshot is not None: results_queue.append(_make_result([snapshot]))
    else: results_queue.append(_make_result([]))
    if relatives is not None:
        results_queue.append(_make_result(relatives))
        results_queue.append(_make_result([]))
        results_queue.append(_make_result([]))
    else:
        results_queue.append(_make_result([]))
        results_queue.append(_make_result([]))
    idx = [0]
    async def _execute(stmt, *args, **kwargs):
        i = idx[0]; idx[0] += 1
        return results_queue[i] if i < len(results_queue) else _make_result([])
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock(); session.delete = AsyncMock()
    session.flush = AsyncMock(); session.add = MagicMock()
    return session

def _override_db(session):
    async def _dep(): yield session
    return _dep

@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()

class TestGetFamilyTree:
    def test_returns_404_for_unknown_person(self):
        session = _make_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}/family-tree")
        assert r.status_code == 404

    def test_returns_pending_when_no_snapshot(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_returns_tree_when_snapshot_exists(self):
        pid = uuid.uuid4()
        snapshot = _make_snapshot(pid)
        session = _make_session(person=_make_person(pid), snapshot=snapshot)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree")
        assert r.status_code == 200
        data = r.json()
        assert "tree" in data
        assert data["source_count"] == 3
        assert data["is_stale"] is False

    def test_returns_pending_when_snapshot_is_stale(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=_make_snapshot(pid, stale=True))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_invalid_uuid_returns_400(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons/not-a-uuid/family-tree")
        assert r.status_code == 400

class TestTriggerFamilyTreeBuild:
    def test_queues_rebuild(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(f"/persons/{pid}/family-tree/build")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["person_id"] == str(pid)

    def test_returns_404_for_unknown_person(self):
        session = _make_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(f"/persons/{uuid.uuid4()}/family-tree/build")
        assert r.status_code == 404

class TestGetFamilyTreeStatus:
    def test_status_not_built(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/status")
        assert r.status_code == 200
        data = r.json()
        assert data["built"] is False
        assert data["source_count"] == 0

    def test_status_built(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=_make_snapshot(pid))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/status")
        assert r.status_code == 200
        data = r.json()
        assert data["built"] is True
        assert data["depth_ancestors"] == 2
        assert data["depth_descendants"] == 1
        assert data["source_count"] == 3

    def test_status_stale(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=_make_snapshot(pid, stale=True))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/status")
        assert r.status_code == 200
        assert r.json()["is_stale"] is True

class TestGetRelatives:
    def test_empty_relatives(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), relatives=[])
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/relatives")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["relatives"] == []

    def test_returns_404_for_unknown_person(self):
        session = _make_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}/relatives")
        assert r.status_code == 404

class TestGetFamilyTreeGedcom:
    def test_returns_404_when_no_tree(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/gedcom")
        assert r.status_code == 404

    def test_returns_gedcom_text(self):
        pid = uuid.uuid4()
        session = _make_session(person=_make_person(pid), snapshot=_make_snapshot(pid))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/gedcom")
        assert r.status_code == 200
        assert "0 HEAD" in r.text
        assert "0 TRLR" in r.text

class TestGenerateGedcom:
    def test_empty_tree_produces_valid_gedcom(self):
        from modules.export.gedcom import generate_gedcom
        tree_json = {"root_person_id": "abc123", "nodes": {}, "edges": []}
        result = generate_gedcom(tree_json, "abc123")
        assert result.startswith("0 HEAD")
        assert "0 TRLR" in result

    def test_single_person_produces_indi_record(self):
        from modules.export.gedcom import generate_gedcom
        pid = "11111111-0000-0000-0000-000000000000"
        tree_json = {"root_person_id": pid, "nodes": {pid: {"id": pid, "name": "John Doe", "birth_date": "1900-01-15", "is_root": True}}, "edges": []}
        result = generate_gedcom(tree_json, pid)
        assert "INDI" in result
        assert "John" in result
        assert "Doe" in result
        assert "1900" in result

    def test_spouse_produces_fam_record(self):
        from modules.export.gedcom import generate_gedcom
        p1 = "11111111-0000-0000-0000-000000000001"
        p2 = "22222222-0000-0000-0000-000000000002"
        tree_json = {
            "root_person_id": p1,
            "nodes": {p1: {"id": p1, "name": "John Doe", "birth_date": None, "is_root": True},
                      p2: {"id": p2, "name": "Jane Doe", "birth_date": None, "is_root": False}},
            "edges": [{"from": p1, "to": p2, "rel_type": "spouse_of"}],
        }
        result = generate_gedcom(tree_json, p1)
        assert "FAM" in result
