"""
test_persons_family_tree_wave6.py — Coverage for family-tree endpoints in persons.py.

Covers:
  GET  /persons/{id}/family-tree
  POST /persons/{id}/family-tree/build
  GET  /persons/{id}/family-tree/status
  GET  /persons/{id}/relatives  (including loop body lines)
  GET  /persons/{id}/family-tree/gedcom

Also covers persons.py line 371 (order_by branch in _fetch helper).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_person(pid=None, name="Test Person"):
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.full_name = name
    p.date_of_birth = None
    p.default_risk_score = 0.1
    p.behavioural_risk = 0.0
    p.darkweb_exposure = 0.0
    p.relationship_score = 0.0
    p.source_reliability = 1.0
    p.composite_quality = 0.9
    p.corroboration_count = 1
    p.verification_status = "verified"
    p.created_at = datetime.now(UTC)
    p.updated_at = datetime.now(UTC)
    p.merged_into = None
    p.meta = {}
    return p


def _make_snapshot(root_id, stale=False):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.root_person_id = root_id
    s.tree_json = {
        "root_person_id": str(root_id),
        "nodes": {
            str(root_id): {"id": str(root_id), "name": "Test Person", "birth_date": None}
        },
        "edges": [],
    }
    s.depth_ancestors = 2
    s.depth_descendants = 1
    s.source_count = 3
    s.built_at = datetime.now(UTC)
    s.is_stale = stale
    return s


def _make_rel(a_id, b_id, rel_type="sibling_of", score=0.8):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.person_a_id = a_id
    r.person_b_id = b_id
    r.rel_type = rel_type
    r.score = score
    return r


def _scalars_result(items):
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    r.scalars.return_value.first.return_value = items[0] if items else None
    r.scalar.return_value = None
    r.scalar_one.return_value = len(items)
    r.scalar_one_or_none.return_value = items[0] if items else None
    return r


def _make_snapshot_session(person=None, snapshot=None):
    """Session for endpoints that make one execute() returning a snapshot."""
    session = AsyncMock()

    async def _get(model, pk):
        return person

    session.get = AsyncMock(side_effect=_get)
    session.commit = AsyncMock()
    session.add = MagicMock()

    items = [snapshot] if snapshot is not None else []
    session.execute = AsyncMock(return_value=_scalars_result(items))
    return session


def _make_rels_session(person=None, rels=None):
    """Session for /relatives endpoint — first execute returns rels."""
    session = AsyncMock()

    async def _get(model, pk):
        return person

    session.get = AsyncMock(side_effect=_get)

    items = rels or []
    idx = [0]

    async def _execute(stmt, *args, **kwargs):
        i = idx[0]
        idx[0] += 1
        if i == 0:
            return _scalars_result(items)
        return _scalars_result([])

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _override_db(session):
    async def _dep():
        yield session
    return _dep


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


# ── GET /persons/{id}/family-tree ─────────────────────────────────────────────


class TestGetFamilyTree:
    def test_unknown_person_returns_404(self):
        session = _make_snapshot_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}/family-tree")
        assert r.status_code == 404

    def test_no_snapshot_returns_pending(self):
        pid = uuid.uuid4()
        session = _make_snapshot_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_ready_snapshot_returns_tree_data(self):
        pid = uuid.uuid4()
        snapshot = _make_snapshot(pid, stale=False)
        session = _make_snapshot_session(person=_make_person(pid), snapshot=snapshot)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree")
        assert r.status_code == 200
        data = r.json()
        assert "tree" in data
        assert data["source_count"] == 3
        assert data["is_stale"] is False

    def test_stale_snapshot_returns_pending(self):
        pid = uuid.uuid4()
        snapshot = _make_snapshot(pid, stale=True)
        session = _make_snapshot_session(person=_make_person(pid), snapshot=snapshot)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_invalid_uuid_returns_400(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons/not-a-uuid/family-tree")
        assert r.status_code == 400


# ── POST /persons/{id}/family-tree/build ─────────────────────────────────────


class TestTriggerFamilyTreeBuild:
    def test_queues_build_for_known_person(self):
        pid = uuid.uuid4()
        session = _make_snapshot_session(person=_make_person(pid))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(f"/persons/{pid}/family-tree/build")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["person_id"] == str(pid)

    def test_unknown_person_returns_404(self):
        session = _make_snapshot_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(f"/persons/{uuid.uuid4()}/family-tree/build")
        assert r.status_code == 404


# ── GET /persons/{id}/family-tree/status ─────────────────────────────────────


class TestFamilyTreeStatus:
    def test_not_built_returns_metadata_with_built_false(self):
        pid = uuid.uuid4()
        session = _make_snapshot_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/status")
        assert r.status_code == 200
        data = r.json()
        assert data["built"] is False
        assert data["source_count"] == 0

    def test_built_snapshot_returns_full_metadata(self):
        pid = uuid.uuid4()
        snapshot = _make_snapshot(pid, stale=False)
        session = _make_snapshot_session(person=_make_person(pid), snapshot=snapshot)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/status")
        assert r.status_code == 200
        data = r.json()
        assert data["built"] is True
        assert data["depth_ancestors"] == 2
        assert data["depth_descendants"] == 1
        assert data["source_count"] == 3

    def test_stale_snapshot_is_stale_true(self):
        pid = uuid.uuid4()
        snapshot = _make_snapshot(pid, stale=True)
        session = _make_snapshot_session(person=_make_person(pid), snapshot=snapshot)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/status")
        assert r.status_code == 200
        assert r.json()["is_stale"] is True


# ── GET /persons/{id}/relatives ───────────────────────────────────────────────


class TestGetRelatives:
    def test_unknown_person_returns_404(self):
        session = _make_rels_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}/relatives")
        assert r.status_code == 404

    def test_empty_relatives_returns_total_zero(self):
        pid = uuid.uuid4()
        session = _make_rels_session(person=_make_person(pid), rels=[])
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/relatives")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["relatives"] == []

    def test_person_is_person_a_returns_person_b_as_other(self):
        """Loop body: person_a == uid → other_id = person_b_id."""
        pid = uuid.uuid4()
        other_pid = uuid.uuid4()
        rel = _make_rel(pid, other_pid, rel_type="sibling_of", score=0.9)
        session = _make_rels_session(person=_make_person(pid), rels=[rel])
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/relatives")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["relatives"][0]["person_id"] == str(other_pid)
        assert data["relatives"][0]["rel_type"] == "sibling_of"

    def test_person_is_person_b_returns_person_a_as_other(self):
        """Loop body else branch: person_b == uid → other_id = person_a_id."""
        pid = uuid.uuid4()
        other_pid = uuid.uuid4()
        # pid is person_b
        rel = _make_rel(other_pid, pid, rel_type="child_of", score=0.7)
        session = _make_rels_session(person=_make_person(pid), rels=[rel])
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/relatives")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["relatives"][0]["person_id"] == str(other_pid)
        assert data["relatives"][0]["rel_type"] == "child_of"


# ── GET /persons/{id}/family-tree/gedcom ─────────────────────────────────────


class TestFamilyTreeGedcom:
    def test_no_snapshot_returns_404(self):
        pid = uuid.uuid4()
        session = _make_snapshot_session(person=_make_person(pid), snapshot=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/gedcom")
        assert r.status_code == 404

    def test_snapshot_returns_valid_gedcom(self):
        pid = uuid.uuid4()
        snapshot = _make_snapshot(pid, stale=False)
        session = _make_snapshot_session(person=_make_person(pid), snapshot=snapshot)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/family-tree/gedcom")
        assert r.status_code == 200
        assert "0 HEAD" in r.text
        assert "0 TRLR" in r.text

    def test_unknown_person_returns_404(self):
        session = _make_snapshot_session(person=None)
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}/family-tree/gedcom")
        assert r.status_code == 404


# ── GET /persons/{id} order_by branch (line 371) ──────────────────────────────


def test_get_person_full_profile_triggers_order_by_branch():
    """Line 371: GET /persons/{id} invokes _fetch() with order_by parameter."""
    pid = uuid.uuid4()
    person = _make_person(pid)

    session = AsyncMock()
    session.get = AsyncMock(return_value=person)
    session.execute = AsyncMock(return_value=_scalars_result([]))

    app.dependency_overrides[db_session] = _override_db(session)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(f"/persons/{pid}")

    assert r.status_code == 200


# ── GEDCOM module unit tests ──────────────────────────────────────────────────


class TestGedcomModule:
    def test_empty_tree_produces_head_and_trlr(self):
        from modules.export.gedcom import generate_gedcom

        result = generate_gedcom({"nodes": {}, "edges": []}, "abc")
        assert result.startswith("0 HEAD")
        assert "0 TRLR" in result

    def test_single_person_indi_record(self):
        from modules.export.gedcom import generate_gedcom

        pid = "11111111-0000-0000-0000-000000000000"
        result = generate_gedcom(
            {"nodes": {pid: {"name": "John Doe", "birth_date": "1900-01-15"}}, "edges": []},
            pid,
        )
        assert "INDI" in result
        assert "John" in result
        assert "1900" in result

    def test_spouse_of_edge_produces_fam_record(self):
        from modules.export.gedcom import generate_gedcom

        p1, p2 = "aaa", "bbb"
        result = generate_gedcom(
            {
                "nodes": {p1: {"name": "Alice"}, p2: {"name": "Bob"}},
                "edges": [{"from": p1, "to": p2, "rel_type": "spouse_of"}],
            },
            p1,
        )
        assert "FAM" in result
        assert "HUSB" in result
        assert "WIFE" in result

    def test_format_gedcom_date_full_iso(self):
        from modules.export.gedcom import _format_gedcom_date

        result = _format_gedcom_date("1900-01-15")
        assert "JAN" in result
        assert "1900" in result

    def test_format_gedcom_date_year_only(self):
        from modules.export.gedcom import _format_gedcom_date

        assert _format_gedcom_date("1950") == "1950"

    def test_format_gedcom_date_empty(self):
        from modules.export.gedcom import _format_gedcom_date

        assert _format_gedcom_date("") == ""
