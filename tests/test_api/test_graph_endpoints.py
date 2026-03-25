"""Tests for Phase 3 graph endpoints and EntityGraphBuilder methods."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph.entity_graph import EntityGraphBuilder


# ── Helpers ──────────────────────────────────────────────────────────────────


def _scalars_result(items):
    sm = MagicMock()
    sm.all.return_value = items
    rm = MagicMock()
    rm.scalars.return_value = sm
    return rm


def _scalar_result(value):
    rm = MagicMock()
    rm.scalar.return_value = value
    return rm


def _empty():
    return _scalars_result([])


def _make_session(side_effects):
    s = AsyncMock()
    s.execute = AsyncMock(side_effect=side_effects)
    return s


def _make_person(name="Alice"):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = name
    p.default_risk_score = 0.3
    return p


# ── Task 1: get_nodes_paginated ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_nodes_paginated_returns_list():
    person = _make_person("Alice")
    session = _make_session([_scalars_result([person])])
    builder = EntityGraphBuilder()
    result = await builder.get_nodes_paginated(session, limit=500, offset=0)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "person"
    assert result[0]["label"] == "Alice"


@pytest.mark.asyncio
async def test_get_nodes_paginated_entity_type_filter():
    person = _make_person("Bob")
    session = _make_session([_scalars_result([person])])
    builder = EntityGraphBuilder()
    result = await builder.get_nodes_paginated(
        session, limit=500, offset=0, entity_types=["person"]
    )
    assert all(n["type"] == "person" for n in result)


@pytest.mark.asyncio
async def test_get_nodes_paginated_empty():
    session = _make_session([_empty()])
    builder = EntityGraphBuilder()
    result = await builder.get_nodes_paginated(session, limit=500, offset=0)
    assert result == []


# ── Task 2: get_edges_paginated ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_edges_paginated_returns_list():
    rel = MagicMock()
    rel.person_a_id = uuid.uuid4()
    rel.person_b_id = uuid.uuid4()
    rel.rel_type = "associate"
    rel.score = 0.75
    session = _make_session([_scalars_result([rel])])
    builder = EntityGraphBuilder()
    result = await builder.get_edges_paginated(session, limit=1000, offset=0)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "associate"
    assert result[0]["source"] == str(rel.person_a_id)
    assert result[0]["target"] == str(rel.person_b_id)


@pytest.mark.asyncio
async def test_get_edges_paginated_empty():
    session = _make_session([_empty()])
    builder = EntityGraphBuilder()
    result = await builder.get_edges_paginated(session, limit=1000, offset=0)
    assert result == []


@pytest.mark.asyncio
async def test_get_edges_paginated_confidence_fallback():
    rel = MagicMock()
    rel.person_a_id = uuid.uuid4()
    rel.person_b_id = uuid.uuid4()
    rel.rel_type = "family"
    rel.score = None  # no score set
    session = _make_session([_scalars_result([rel])])
    builder = EntityGraphBuilder()
    result = await builder.get_edges_paginated(session, limit=1000, offset=0)
    assert result[0]["confidence"] == 0.5


# ── Task 3: find_shortest_path ────────────────────────────────────────────────


def _make_rel(a_id, b_id, rel_type="associate", score=0.8):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.person_a_id = a_id
    r.person_b_id = b_id
    r.rel_type = rel_type
    r.score = score
    return r


@pytest.mark.asyncio
async def test_find_shortest_path_direct_connection():
    """A — B directly connected → path length 2 (both nodes)."""
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    str_a, str_b = str(id_a), str(id_b)
    rel = _make_rel(id_a, id_b)

    session = _make_session([_scalars_result([rel])])
    builder = EntityGraphBuilder()
    result = await builder.find_shortest_path(
        str_a, str_b, session, entity_types=None, max_hops=6
    )
    assert result["path"] is not None
    assert str_a in result["path"]
    assert str_b in result["path"]
    assert len(result["path"]) == 2


@pytest.mark.asyncio
async def test_find_shortest_path_no_path():
    """A and C have no connection → returns path=null."""
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    id_c = uuid.uuid4()
    # Only A-B edge, no edge to C
    rel = _make_rel(id_a, id_b)
    session = _make_session([_scalars_result([rel])])
    builder = EntityGraphBuilder()
    result = await builder.find_shortest_path(
        str(id_a), str(id_c), session, entity_types=None, max_hops=6
    )
    assert result["path"] is None
    assert result["reason"] == "no_path_within_max_hops"


@pytest.mark.asyncio
async def test_find_shortest_path_max_hops_enforced():
    """Path longer than max_hops is rejected."""
    # Build a chain: A-B-C-D-E-F-G-H (7 hops deep)
    ids = [uuid.uuid4() for _ in range(8)]
    rels = [_make_rel(ids[i], ids[i + 1]) for i in range(7)]
    session = _make_session([_scalars_result(rels)])
    builder = EntityGraphBuilder()
    result = await builder.find_shortest_path(
        str(ids[0]), str(ids[7]), session, entity_types=None, max_hops=3
    )
    assert result["path"] is None
    assert result["reason"] == "no_path_within_max_hops"


@pytest.mark.asyncio
async def test_find_shortest_path_max_hops_hard_cap_raises():
    """max_hops > 10 should raise ValueError."""
    session = AsyncMock()
    builder = EntityGraphBuilder()
    with pytest.raises(ValueError, match="max_hops"):
        await builder.find_shortest_path(
            str(uuid.uuid4()), str(uuid.uuid4()), session, entity_types=None, max_hops=11
        )


# ── Task 4: expand_entity ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_entity_person_returns_neighbors():
    """Expanding a person node returns 1-hop address and relationship nodes."""
    person_id = uuid.uuid4()
    pid_str = str(person_id)

    neighbor_id = uuid.uuid4()
    rel = _make_rel(person_id, neighbor_id)
    person = _make_person("Alice")
    person.id = person_id

    addr = MagicMock()
    addr.id = uuid.uuid4()
    addr.person_id = person_id
    addr.street = "1 Main St"
    addr.city = "Dallas"
    addr.state_province = "TX"

    # execute calls in expand_entity (via build_person_graph depth=1):
    # 1. fetch the target person
    # 2. addresses
    # 3. identifiers
    # 4. employment
    # 5. social profiles
    # 6. relationships
    session = _make_session([
        _scalars_result([person]),
        _scalars_result([addr]),
        _empty(),
        _empty(),
        _empty(),
        _scalars_result([rel]),
    ])
    builder = EntityGraphBuilder()
    result = await builder.expand_entity("person", pid_str, session)
    assert "nodes" in result
    assert "edges" in result
    node_ids = [n["id"] for n in result["nodes"]]
    assert pid_str in node_ids
    assert f"addr:{addr.id}" in node_ids


@pytest.mark.asyncio
async def test_expand_entity_unknown_type_raises():
    session = AsyncMock()
    builder = EntityGraphBuilder()
    with pytest.raises(ValueError, match="Unsupported entity_type"):
        await builder.expand_entity("crypto_wallet", str(uuid.uuid4()), session)


# ── Task 5: person network includes non-person entity nodes ───────────────────


@pytest.mark.asyncio
async def test_build_person_graph_includes_address_and_company_nodes():
    """build_person_graph at depth=1 must return address and company stub nodes."""
    person_id = uuid.uuid4()
    person = _make_person("Eve")
    person.id = person_id

    addr = MagicMock()
    addr.id = uuid.uuid4()
    addr.person_id = person_id
    addr.street = "50 Oak Ave"
    addr.city = "Houston"
    addr.state_province = "TX"

    emp = MagicMock()
    emp.person_id = person_id
    emp.employer_name = "Wolf Corp"
    emp.job_title = "CEO"
    emp.is_current = True

    ident_email = MagicMock()
    ident_email.id = uuid.uuid4()
    ident_email.person_id = person_id
    ident_email.type = "email"
    ident_email.value = "eve@wolfcorp.com"
    ident_email.confidence = 1.0

    session = _make_session([
        _scalars_result([person]),
        _scalars_result([addr]),
        _scalars_result([ident_email]),
        _scalars_result([emp]),
        _empty(),
        _empty(),
    ])
    from modules.graph.entity_graph import EntityGraphBuilder
    builder = EntityGraphBuilder()
    graph = await builder.build_person_graph(str(person_id), session, depth=1)

    node_types = {n["type"] for n in graph["nodes"]}
    assert "address" in node_types, "address nodes must be included"
    assert "company" in node_types, "company nodes must be included"
    assert "email" in node_types, "email nodes must be included"
    edge_types = {e["type"] for e in graph["edges"]}
    assert "lives_at" in edge_types
    assert "officer" in edge_types
    assert "has_email" in edge_types


@pytest.mark.asyncio
async def test_person_network_response_has_node_and_edge_count():
    """
    Verifies api/routes/graph.py person_network handler exposes node_count and edge_count.
    This test calls the handler directly with a mocked graph builder.
    """
    from unittest.mock import patch, AsyncMock as AM
    from api.routes.graph import person_network

    fake_graph = {
        "nodes": [{"id": "a", "type": "person", "label": "A", "risk_score": 0.1}],
        "edges": [{"source": "a", "target": "b", "type": "knows", "confidence": 0.9}],
    }

    fake_session = AsyncMock()

    with patch("api.routes.graph._graph_builder") as mock_builder:
        mock_builder.build_person_graph = AM(return_value=fake_graph)
        response = await person_network(
            person_id="aaaaaaaa-0000-0000-0000-000000000001",
            depth=1,
            session=fake_session,
        )

    assert response["node_count"] == 1
    assert response["edge_count"] == 1


# ── Task 6: GET /graph/nodes, GET /graph/edges ───────────────────────────────


@pytest.mark.asyncio
async def test_graph_nodes_endpoint_returns_nodes_key():
    from unittest.mock import patch, AsyncMock as AM
    from api.routes.graph import graph_nodes

    fake_nodes = [{"id": "p:1", "type": "person", "label": "Alice", "risk_score": 0.2}]
    fake_session = AsyncMock()

    with patch("api.routes.graph._graph_builder") as mb:
        mb.get_nodes_paginated = AM(return_value=fake_nodes)
        response = await graph_nodes(
            limit=500, offset=0, entity_types=None, session=fake_session
        )

    assert "nodes" in response
    assert response["count"] == 1
    assert response["nodes"][0]["type"] == "person"


@pytest.mark.asyncio
async def test_graph_edges_endpoint_returns_edges_key():
    from unittest.mock import patch, AsyncMock as AM
    from api.routes.graph import graph_edges

    fake_edges = [{"source": "a", "target": "b", "type": "associate", "confidence": 0.7}]
    fake_session = AsyncMock()

    with patch("api.routes.graph._graph_builder") as mb:
        mb.get_edges_paginated = AM(return_value=fake_edges)
        response = await graph_edges(limit=1000, offset=0, session=fake_session)

    assert "edges" in response
    assert response["count"] == 1


# ── Task 7: GET /graph/path, GET /graph/entity/{type}/{id}/expand ─────────────


@pytest.mark.asyncio
async def test_graph_path_endpoint_returns_path():
    from unittest.mock import patch, AsyncMock as AM
    from api.routes.graph import graph_path

    fake_result = {"path": ["id-a", "id-b"], "edges": []}
    fake_session = AsyncMock()

    with patch("api.routes.graph._graph_builder") as mb:
        mb.find_shortest_path = AM(return_value=fake_result)
        response = await graph_path(
            from_id="id-a",
            to_id="id-b",
            entity_types=None,
            max_hops=6,
            session=fake_session,
        )

    assert response["path"] == ["id-a", "id-b"]


@pytest.mark.asyncio
async def test_graph_path_endpoint_rejects_max_hops_above_10():
    from api.routes.graph import graph_path
    from fastapi import HTTPException as HE
    fake_session = AsyncMock()
    with pytest.raises(HE) as exc_info:
        await graph_path(
            from_id="id-a",
            to_id="id-b",
            entity_types=None,
            max_hops=11,
            session=fake_session,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_graph_expand_endpoint_returns_nodes_and_edges():
    from unittest.mock import patch, AsyncMock as AM
    from api.routes.graph import graph_expand

    fake_result = {
        "nodes": [{"id": "person:abc", "type": "person", "label": "Bob", "risk_score": 0.1}],
        "edges": [],
    }
    fake_session = AsyncMock()

    with patch("api.routes.graph._graph_builder") as mb:
        mb.expand_entity = AM(return_value=fake_result)
        response = await graph_expand(
            entity_type="person",
            entity_id="abc",
            session=fake_session,
        )

    assert "nodes" in response
    assert "edges" in response
