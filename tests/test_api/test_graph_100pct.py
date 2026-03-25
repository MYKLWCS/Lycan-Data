"""
test_graph_100pct.py — Coverage for api/routes/graph.py exception paths.

Targets:
  - Lines 139-141: except Exception in graph_nodes → HTTP 500
  - Lines 156-158: except Exception in graph_edges → HTTP 500
  - Lines 180-184: except Exception (non-ValueError) in graph_path → HTTP 500
  - Lines 197-201: except Exception in graph_expand → HTTP 500
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import db_session
from api.routes.graph import router


def _make_session():
    session = AsyncMock()
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    r.scalar_one.return_value = 0
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


# ---------------------------------------------------------------------------
# graph_nodes — except Exception (lines 139-141)
# ---------------------------------------------------------------------------


def test_graph_nodes_exception_returns_500():
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.get_nodes_paginated = AsyncMock(side_effect=RuntimeError("db down"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/nodes")
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# graph_edges — except Exception (lines 156-158)
# ---------------------------------------------------------------------------


def test_graph_edges_exception_returns_500():
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.get_edges_paginated = AsyncMock(side_effect=RuntimeError("db down"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/edges")
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# graph_path — except Exception non-ValueError (lines 182-184)
# ---------------------------------------------------------------------------


def test_graph_path_generic_exception_returns_500():
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.find_shortest_path = AsyncMock(side_effect=RuntimeError("db down"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/path?from=abc&to=xyz")
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# graph_expand — except Exception (lines 199-201)
# ---------------------------------------------------------------------------


def test_graph_expand_generic_exception_returns_500():
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.expand_entity = AsyncMock(side_effect=RuntimeError("db down"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/graph/entity/person/some-id/expand")
    assert r.status_code == 500
