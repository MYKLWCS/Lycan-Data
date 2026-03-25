"""
test_graph_wave6.py — Coverage for api/routes/graph.py missing lines.

Targets:
  - Lines 42-43  : search_company happy path
  - Lines 55-56  : company_network happy path
  - Lines 72-76  : person_network ValueError + generic Exception
  - Lines 93-101 : person_companies ValueError + generic Exception + return
  - Lines 110-118: detect_fraud_rings generic Exception + return
  - Line 181     : graph_path ValueError → HTTP 400
  - Line 198     : graph_expand ValueError → HTTP 400
  - Lines 213-222: shared_connections validation (<2 ids) + generic Exception + return
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import db_session
from api.routes.graph import router

# ── App fixture ───────────────────────────────────────────────────────────────


def _make_session():
    session = AsyncMock()
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=r)
    session.get = AsyncMock(return_value=None)
    return session


def _make_app(session):
    app = FastAPI()
    app.include_router(router, prefix="/graph")

    async def _dep():
        yield session

    app.dependency_overrides[db_session] = _dep
    return app


# ── search_company happy path (lines 42-43) ───────────────────────────────────


def test_search_company_returns_companies_and_count():
    """Lines 42-43: search_company calls engine and returns companies list."""
    session = _make_session()
    app = _make_app(session)

    fake_company = {"id": "c1", "legal_name": "Acme Corp"}

    with patch("api.routes.graph._company_engine") as mock_engine:
        mock_engine.search_company = AsyncMock(return_value=[fake_company])
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/company/search?name=Acme")

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert len(data["companies"]) == 1


def test_search_company_empty_result():
    """search_company returns count=0 when no companies found."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._company_engine") as mock_engine:
        mock_engine.search_company = AsyncMock(return_value=[])
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/company/search?name=NoSuchCorp")

    assert r.status_code == 200
    assert r.json()["count"] == 0


# ── company_network happy path (lines 55-56) ──────────────────────────────────


def test_company_network_returns_nodes_edges_and_name():
    """Lines 55-56: company_network returns nodes, edges, and company_name."""
    session = _make_session()
    app = _make_app(session)

    fake_network = {
        "nodes": [{"id": "p1", "label": "Alice"}],
        "edges": [{"source": "p1", "target": "p2", "type": "associate"}],
    }

    with patch("api.routes.graph._company_engine") as mock_engine:
        mock_engine.get_company_network = AsyncMock(return_value=fake_network)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/company/network?name=Acme")

    assert r.status_code == 200
    data = r.json()
    assert data["company_name"] == "Acme"
    assert len(data["nodes"]) == 1
    assert len(data["edges"]) == 1


# ── person_network ValueError (lines 72-73) ───────────────────────────────────


def test_person_network_value_error_returns_400():
    """Lines 72-73: ValueError in build_person_graph raises HTTP 400."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.build_person_graph = AsyncMock(side_effect=ValueError("invalid person_id"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/person/bad-uuid/network")

    assert r.status_code == 400
    assert "invalid person_id" in r.json()["detail"]


def test_person_network_generic_exception_returns_500():
    """Lines 74-76: Generic Exception in build_person_graph raises HTTP 500."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.build_person_graph = AsyncMock(side_effect=RuntimeError("db exploded"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/person/some-id/network")

    assert r.status_code == 500


# ── person_companies ValueError + generic Exception (lines 93-101) ────────────


def test_person_companies_value_error_returns_400():
    """Lines 95-96: ValueError from get_person_companies → HTTP 400."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._company_engine") as mock_engine:
        mock_engine.get_person_companies = AsyncMock(side_effect=ValueError("bad person id"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/person/bad-id/companies")

    assert r.status_code == 400
    assert "bad person id" in r.json()["detail"]


def test_person_companies_generic_exception_returns_500():
    """Lines 97-99: Generic exception from get_person_companies → HTTP 500."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._company_engine") as mock_engine:
        mock_engine.get_person_companies = AsyncMock(side_effect=RuntimeError("db crash"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/person/some-id/companies")

    assert r.status_code == 500


def test_person_companies_happy_path():
    """Lines 101-104: Successful person_companies returns person_id and companies."""
    session = _make_session()
    app = _make_app(session)

    fake_companies = [{"id": "c1", "legal_name": "Acme"}]

    with patch("api.routes.graph._company_engine") as mock_engine:
        mock_engine.get_person_companies = AsyncMock(return_value=fake_companies)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/person/some-id/companies")

    assert r.status_code == 200
    data = r.json()
    assert data["person_id"] == "some-id"
    assert len(data["companies"]) == 1


# ── detect_fraud_rings generic Exception + return (lines 110-121) ─────────────


def test_detect_fraud_rings_exception_returns_500():
    """Lines 114-116: Generic exception in detect_fraud_rings → HTTP 500."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.detect_fraud_rings = AsyncMock(side_effect=RuntimeError("cluster failed"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/graph/fraud-rings", json={"min_connections": 3})

    assert r.status_code == 500


def test_detect_fraud_rings_happy_path():
    """Lines 118-121: Successful detect_fraud_rings returns rings and count."""
    session = _make_session()
    app = _make_app(session)

    fake_rings = [
        {
            "persons": ["p1", "p2", "p3"],
            "shared_element": "address:5 Oak St, Dallas",
            "risk_score": 0.5,
        }
    ]

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.detect_fraud_rings = AsyncMock(return_value=fake_rings)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/graph/fraud-rings", json={"min_connections": 3})

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert len(data["rings"]) == 1


# ── graph_path ValueError → HTTP 400 (line 181) ───────────────────────────────


def test_graph_path_value_error_returns_400():
    """Line 181: ValueError from find_shortest_path → HTTP 400."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.find_shortest_path = AsyncMock(side_effect=ValueError("node not found"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/path?from=id-a&to=id-b")

    assert r.status_code == 400
    assert "node not found" in r.json()["detail"]


def test_graph_path_with_entity_types_filter():
    """graph_path with entity_types param splits the string correctly."""
    session = _make_session()
    app = _make_app(session)

    fake_result = {"path": ["a", "b"], "edges": []}

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.find_shortest_path = AsyncMock(return_value=fake_result)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/path?from=id-a&to=id-b&entity_types=person,company")

    assert r.status_code == 200


# ── graph_expand ValueError → HTTP 400 (line 198) ────────────────────────────


def test_graph_expand_value_error_returns_400():
    """Line 198: ValueError from expand_entity → HTTP 400."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.expand_entity = AsyncMock(
            side_effect=ValueError("Unsupported entity_type: 'bogus'")
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/entity/bogus/some-id/expand")

    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


# ── shared_connections validation + exception + return (lines 213-222) ────────


def test_shared_connections_fewer_than_2_ids_returns_400():
    """Lines 213-214: Less than 2 person_ids → HTTP 400."""
    session = _make_session()
    app = _make_app(session)

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/graph/shared-connections", json={"person_ids": ["only-one"]})

    assert r.status_code == 400
    assert "2 person_ids" in r.json()["detail"]


def test_shared_connections_exception_returns_500():
    """Lines 218-220: Generic exception in find_shared_connections → HTTP 500."""
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.find_shared_connections = AsyncMock(side_effect=RuntimeError("db error"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post(
                "/graph/shared-connections",
                json={"person_ids": ["id-a", "id-b"]},
            )

    assert r.status_code == 500


def test_shared_connections_happy_path():
    """Lines 222-225: Successful shared_connections returns connections and count."""
    session = _make_session()
    app = _make_app(session)

    fake_connections = [
        {
            "type": "phone",
            "value": "555-1234",
            "person_ids": ["id-a", "id-b"],
            "risk_implication": "shared_identifier",
        }
    ]

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.find_shared_connections = AsyncMock(return_value=fake_connections)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post(
                "/graph/shared-connections",
                json={"person_ids": ["id-a", "id-b"]},
            )

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["connections"][0]["type"] == "phone"
