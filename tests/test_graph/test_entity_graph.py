"""Tests for modules/graph/entity_graph.py — EntityGraphBuilder.

All DB interaction is mocked via AsyncMock; no live PostgreSQL required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.graph.entity_graph import EntityGraphBuilder, _edge, _person_node, _stub_node

# ---------------------------------------------------------------------------
# Pure helper tests (no DB)
# ---------------------------------------------------------------------------


def test_person_node_uses_full_name():
    p = MagicMock()
    p.id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    p.full_name = "Alice Smith"
    p.default_risk_score = 0.7
    node = _person_node(p)
    assert node["label"] == "Alice Smith"
    assert node["type"] == "person"
    assert node["risk_score"] == 0.7


def test_person_node_fallback_when_no_name():
    p = MagicMock()
    p.id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
    p.full_name = None
    p.default_risk_score = None
    node = _person_node(p)
    assert node["label"] == str(p.id)
    assert node["risk_score"] == 0.0


def test_stub_node_structure():
    node = _stub_node("some:id", "phone", "+1-555-0000")
    assert node == {"id": "some:id", "type": "phone", "label": "+1-555-0000", "risk_score": 0.0}


def test_edge_structure():
    e = _edge("src", "tgt", "knows", 0.8)
    assert e == {"source": "src", "target": "tgt", "type": "knows", "confidence": 0.8}


# ---------------------------------------------------------------------------
# Session mock helper
# ---------------------------------------------------------------------------


def _scalars_result(items: list) -> MagicMock:
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


def _make_session(side_effects: list) -> AsyncMock:
    """Return a session whose execute() yields `side_effects` in sequence."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=side_effects)
    return session


def _empty_result() -> MagicMock:
    return _scalars_result([])


# ---------------------------------------------------------------------------
# build_person_graph
# ---------------------------------------------------------------------------


async def test_build_person_graph_returns_nodes_and_edges_keys():
    person_id = str(uuid.uuid4())
    person = MagicMock()
    person.id = uuid.UUID(person_id)
    person.full_name = "Bob"
    person.default_risk_score = 0.2

    # execute is called for: persons, addresses, identifiers, employment, social, relationships
    # (per hop, depth=1 means one pass)
    session = _make_session(
        [
            _scalars_result([person]),  # persons
            _empty_result(),  # addresses
            _empty_result(),  # identifiers
            _empty_result(),  # employment
            _empty_result(),  # social profiles
            _empty_result(),  # relationships
        ]
    )

    builder = EntityGraphBuilder()
    graph = await builder.build_person_graph(person_id, session, depth=1)

    assert "nodes" in graph
    assert "edges" in graph
    assert any(n["id"] == person_id for n in graph["nodes"])


async def test_build_person_graph_address_node_and_edge_created():
    person_id = str(uuid.uuid4())
    person = MagicMock()
    person.id = uuid.UUID(person_id)
    person.full_name = "Carol"
    person.default_risk_score = 0.0

    addr = MagicMock()
    addr.id = uuid.uuid4()
    addr.person_id = person.id
    addr.street = "123 Main St"
    addr.city = "Springfield"
    addr.state_province = "IL"

    session = _make_session(
        [
            _scalars_result([person]),
            _scalars_result([addr]),  # addresses
            _empty_result(),
            _empty_result(),
            _empty_result(),
            _empty_result(),
        ]
    )

    builder = EntityGraphBuilder()
    graph = await builder.build_person_graph(person_id, session, depth=1)

    addr_ids = [n["id"] for n in graph["nodes"] if n["type"] == "address"]
    assert len(addr_ids) == 1
    edge_types = [e["type"] for e in graph["edges"]]
    assert "lives_at" in edge_types


async def test_build_person_graph_employment_creates_company_node():
    person_id = str(uuid.uuid4())
    person = MagicMock()
    person.id = uuid.UUID(person_id)
    person.full_name = "Dave"
    person.default_risk_score = 0.0

    emp = MagicMock()
    emp.person_id = person.id
    emp.employer_name = "Acme Corp"
    emp.job_title = "Engineer"
    emp.is_current = True

    session = _make_session(
        [
            _scalars_result([person]),
            _empty_result(),  # addresses
            _empty_result(),  # identifiers
            _scalars_result([emp]),  # employment
            _empty_result(),  # social
            _empty_result(),  # relationships
        ]
    )

    builder = EntityGraphBuilder()
    graph = await builder.build_person_graph(person_id, session, depth=1)

    company_nodes = [n for n in graph["nodes"] if n["type"] == "company"]
    assert len(company_nodes) == 1
    assert company_nodes[0]["label"] == "Acme Corp"
    edge_types = [e["type"] for e in graph["edges"]]
    assert "officer" in edge_types


# ---------------------------------------------------------------------------
# find_shared_connections
# ---------------------------------------------------------------------------


async def test_find_shared_connections_returns_empty_for_single_person():
    session = AsyncMock()
    builder = EntityGraphBuilder()
    result = await builder.find_shared_connections(["only-one"], session)
    assert result == []


async def test_find_shared_connections_detects_shared_phone():
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())

    shared_phone = "555-1234"
    pid_a_uuid = uuid.UUID(pid_a)
    pid_b_uuid = uuid.UUID(pid_b)

    ident_a = MagicMock()
    ident_a.person_id = pid_a_uuid
    ident_a.type = "phone"
    ident_a.value = shared_phone
    ident_a.normalized_value = shared_phone

    ident_b = MagicMock()
    ident_b.person_id = pid_b_uuid
    ident_b.type = "phone"
    ident_b.value = shared_phone
    ident_b.normalized_value = shared_phone

    session = _make_session(
        [
            _scalars_result([ident_a, ident_b]),  # identifiers
            _empty_result(),  # addresses
            _empty_result(),  # employment
        ]
    )

    builder = EntityGraphBuilder()
    shared = await builder.find_shared_connections([pid_a, pid_b], session)
    assert len(shared) >= 1
    types = [s["type"] for s in shared]
    assert "phone" in types
    assert shared[0]["risk_implication"] == "shared_identifier"


async def test_find_shared_connections_detects_shared_address():
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())
    pid_a_uuid = uuid.UUID(pid_a)
    pid_b_uuid = uuid.UUID(pid_b)

    def _addr(pid):
        a = MagicMock()
        a.person_id = pid
        a.street = "10 Park Lane"
        a.city = "Austin"
        return a

    session = _make_session(
        [
            _empty_result(),  # identifiers
            _scalars_result([_addr(pid_a_uuid), _addr(pid_b_uuid)]),  # addresses
            _empty_result(),  # employment
        ]
    )

    builder = EntityGraphBuilder()
    shared = await builder.find_shared_connections([pid_a, pid_b], session)
    addr_hits = [s for s in shared if s["type"] == "address"]
    assert len(addr_hits) == 1
    assert addr_hits[0]["risk_implication"] == "shared_address"


# ---------------------------------------------------------------------------
# detect_fraud_rings
# ---------------------------------------------------------------------------


async def test_detect_fraud_rings_returns_list():
    session = _make_session(
        [
            _empty_result(),  # addresses
            _empty_result(),  # phones
        ]
    )
    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)
    assert isinstance(rings, list)


async def test_detect_fraud_rings_address_cluster():
    pids = [uuid.uuid4() for _ in range(4)]

    def _addr(pid):
        a = MagicMock()
        a.person_id = pid
        a.street = "99 Fraud Ave"
        a.city = "Riskville"
        return a

    addr_rows = [_addr(p) for p in pids]

    session = _make_session(
        [
            _scalars_result(addr_rows),  # addresses
            _empty_result(),  # phones
        ]
    )

    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)
    assert len(rings) == 1
    ring = rings[0]
    assert "address" in ring["shared_element"]
    assert len(ring["persons"]) == 4
    assert ring["risk_score"] >= 0.4


async def test_detect_fraud_rings_sorted_by_risk_desc():
    # Two address clusters of different sizes → risk scores should be descending
    pids_large = [uuid.uuid4() for _ in range(6)]
    pids_small = [uuid.uuid4() for _ in range(3)]

    def _addr(pid, street):
        a = MagicMock()
        a.person_id = pid
        a.street = street
        a.city = "City"
        return a

    addr_rows = [_addr(p, "Big St") for p in pids_large] + [
        _addr(p, "Small St") for p in pids_small
    ]

    session = _make_session(
        [
            _scalars_result(addr_rows),
            _empty_result(),
        ]
    )

    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)
    assert len(rings) == 2
    assert rings[0]["risk_score"] >= rings[1]["risk_score"]
