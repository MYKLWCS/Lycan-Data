# Knowledge Graph D3 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current table-based graph view in `static/index.html` with a D3.js v7 force-directed SVG graph covering 8 entity types, a real-time filter panel, BFS shortest path, and a Web Worker simulation — backed by 4 new paginated API endpoints.

**Architecture:** `EntityGraphBuilder` gains 4 new async methods (`get_nodes_paginated`, `get_edges_paginated`, `find_shortest_path`, `expand_entity`); these are exposed as `GET /graph/nodes`, `GET /graph/edges`, `GET /graph/path`, and `GET /graph/entity/{type}/{id}/expand` in `api/routes/graph.py`. The existing `GET /graph/person/{id}/network` is extended to include non-person entity nodes. The SPA replaces its `renderGraph()` function with a D3 SVG canvas that loads nodes in pages of 500, offloads force simulation to `static/graph_worker.js` via Web Worker, and renders 8 distinct shapes per entity type with a filter panel and Shift+click shortest-path highlight.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, D3.js v7, Web Worker API

---

### Task 1: EntityGraphBuilder.get_nodes_paginated()

**Files:**
- Modify: `modules/graph/entity_graph.py`
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api/test_graph_endpoints.py
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


async def test_get_nodes_paginated_returns_list():
    person = _make_person("Alice")
    session = _make_session([_scalars_result([person])])
    builder = EntityGraphBuilder()
    result = await builder.get_nodes_paginated(session, limit=500, offset=0)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "person"
    assert result[0]["label"] == "Alice"


async def test_get_nodes_paginated_entity_type_filter():
    person = _make_person("Bob")
    session = _make_session([_scalars_result([person])])
    builder = EntityGraphBuilder()
    result = await builder.get_nodes_paginated(
        session, limit=500, offset=0, entity_types=["person"]
    )
    assert all(n["type"] == "person" for n in result)


async def test_get_nodes_paginated_empty():
    session = _make_session([_empty()])
    builder = EntityGraphBuilder()
    result = await builder.get_nodes_paginated(session, limit=500, offset=0)
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py::test_get_nodes_paginated_returns_list tests/test_api/test_graph_endpoints.py::test_get_nodes_paginated_entity_type_filter tests/test_api/test_graph_endpoints.py::test_get_nodes_paginated_empty -v`

Expected: FAIL with `AttributeError: 'EntityGraphBuilder' object has no attribute 'get_nodes_paginated'`

- [ ] **Step 3: Write minimal implementation**

Add to `EntityGraphBuilder` in `modules/graph/entity_graph.py` (after `detect_fraud_rings`):

```python
# ── New Phase 3 methods ───────────────────────────────────────────────────────

_ENTITY_TYPE_MODELS: dict[str, type] = {}  # populated lazily via _entity_model()


def _entity_model(entity_type: str):
    """Return the SQLAlchemy model for a given entity_type string."""
    from shared.models.address import Address
    from shared.models.identifier import Identifier
    from shared.models.employment import EmploymentHistory
    mapping = {
        "person": Person,
        "address": Address,
        "phone": Identifier,
        "email": Identifier,
        "company": EmploymentHistory,
    }
    return mapping.get(entity_type)


async def get_nodes_paginated(
    self,
    session: AsyncSession,
    limit: int = 500,
    offset: int = 0,
    entity_types: list[str] | None = None,
) -> list[dict]:
    """
    Return a flat page of graph nodes ordered by degree (risk_score desc as proxy).
    Supported entity_types: person, company, address, phone, email.
    When entity_types is None or empty, persons are returned (most-connected first).
    """
    from shared.models.address import Address
    from shared.models.identifier import Identifier
    from shared.models.employment import EmploymentHistory

    allowed = entity_types or ["person"]
    nodes: list[dict] = []

    if "person" in allowed:
        stmt = (
            select(Person)
            .order_by(Person.default_risk_score.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for p in rows:
            nodes.append(_person_node(p))

    if "address" in allowed:
        stmt = select(Address).limit(limit).offset(offset)
        rows = (await session.execute(stmt)).scalars().all()
        for a in rows:
            label = ", ".join(filter(None, [a.street, a.city, a.state_province])) or str(a.id)
            nodes.append(_stub_node(f"addr:{a.id}", "address", label))

    if "phone" in allowed:
        stmt = (
            select(Identifier)
            .where(Identifier.type == "phone")
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for i in rows:
            nodes.append(_stub_node(f"ident:{i.id}", "phone", i.value))

    if "email" in allowed:
        stmt = (
            select(Identifier)
            .where(Identifier.type == "email")
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for i in rows:
            nodes.append(_stub_node(f"ident:{i.id}", "email", i.value))

    if "company" in allowed:
        stmt = (
            select(EmploymentHistory)
            .where(EmploymentHistory.employer_name.isnot(None))
            .distinct(EmploymentHistory.employer_name)
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).scalars().all()
        seen: set[str] = set()
        for e in rows:
            name = e.employer_name or ""
            cid = f"company:{uuid.uuid5(uuid.NAMESPACE_DNS, name.lower().strip())}"
            if cid not in seen:
                seen.add(cid)
                nodes.append(_stub_node(cid, "company", name))

    return nodes[:limit]
```

Then register the method on the class (indent under `EntityGraphBuilder`).

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py::test_get_nodes_paginated_returns_list tests/test_api/test_graph_endpoints.py::test_get_nodes_paginated_entity_type_filter tests/test_api/test_graph_endpoints.py::test_get_nodes_paginated_empty -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/graph/entity_graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: add EntityGraphBuilder.get_nodes_paginated() with entity_type filter"
```

---

### Task 2: EntityGraphBuilder.get_edges_paginated()

**Files:**
- Modify: `modules/graph/entity_graph.py`
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_graph_endpoints.py`:

```python
# ── Task 2: get_edges_paginated ───────────────────────────────────────────────


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


async def test_get_edges_paginated_empty():
    session = _make_session([_empty()])
    builder = EntityGraphBuilder()
    result = await builder.get_edges_paginated(session, limit=1000, offset=0)
    assert result == []


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py::test_get_edges_paginated_returns_list tests/test_api/test_graph_endpoints.py::test_get_edges_paginated_empty tests/test_api/test_graph_endpoints.py::test_get_edges_paginated_confidence_fallback -v`

Expected: FAIL with `AttributeError: 'EntityGraphBuilder' object has no attribute 'get_edges_paginated'`

- [ ] **Step 3: Write minimal implementation**

Add to `EntityGraphBuilder` in `modules/graph/entity_graph.py`:

```python
async def get_edges_paginated(
    self,
    session: AsyncSession,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """
    Return a paginated list of relationship edges between person nodes.
    Each edge: {source, target, type, confidence}.
    """
    stmt = select(Relationship).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        _edge(
            str(r.person_a_id),
            str(r.person_b_id),
            r.rel_type,
            r.score if r.score is not None else 0.5,
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py::test_get_edges_paginated_returns_list tests/test_api/test_graph_endpoints.py::test_get_edges_paginated_empty tests/test_api/test_graph_endpoints.py::test_get_edges_paginated_confidence_fallback -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/graph/entity_graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: add EntityGraphBuilder.get_edges_paginated()"
```

---

### Task 3: EntityGraphBuilder.find_shortest_path() — BFS with entity_types filter and max_hops cap

**Files:**
- Modify: `modules/graph/entity_graph.py`
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_graph_endpoints.py`:

```python
# ── Task 3: find_shortest_path ────────────────────────────────────────────────


def _make_rel(a_id, b_id, rel_type="associate", score=0.8):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.person_a_id = a_id
    r.person_b_id = b_id
    r.rel_type = rel_type
    r.score = score
    return r


async def test_find_shortest_path_direct_connection():
    """A — B directly connected → path length 2 (both nodes)."""
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    str_a, str_b = str(id_a), str(id_b)
    rel = _make_rel(id_a, id_b)

    # BFS calls:
    # 1. load all relationships for adjacency (one SELECT Relationship)
    session = _make_session([_scalars_result([rel])])
    builder = EntityGraphBuilder()
    result = await builder.find_shortest_path(
        str_a, str_b, session, entity_types=None, max_hops=6
    )
    assert result["path"] is not None
    assert str_a in result["path"]
    assert str_b in result["path"]
    assert len(result["path"]) == 2


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


async def test_find_shortest_path_max_hops_hard_cap_raises():
    """max_hops > 10 should raise ValueError."""
    session = AsyncMock()
    builder = EntityGraphBuilder()
    with pytest.raises(ValueError, match="max_hops"):
        await builder.find_shortest_path(
            str(uuid.uuid4()), str(uuid.uuid4()), session, entity_types=None, max_hops=11
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "find_shortest_path" -v`

Expected: FAIL with `AttributeError: 'EntityGraphBuilder' object has no attribute 'find_shortest_path'`

- [ ] **Step 3: Write minimal implementation**

Add to `EntityGraphBuilder` in `modules/graph/entity_graph.py`:

```python
async def find_shortest_path(
    self,
    from_id: str,
    to_id: str,
    session: AsyncSession,
    entity_types: list[str] | None,
    max_hops: int = 6,
) -> dict:
    """
    BFS shortest path between two person nodes.

    entity_types: if provided, only traverse through person nodes whose UUIDs
    are present (non-person entity nodes are never traversal waypoints in the
    current schema — they are leaves). Pass None or ["person"] to traverse all.
    max_hops: maximum number of edges to traverse. Hard cap 10.

    Returns:
        {"path": [id, ...], "edges": [{source, target, type, confidence}]}
        or {"path": null, "reason": "no_path_within_max_hops"}
    """
    if max_hops > 10:
        raise ValueError(f"max_hops must be ≤ 10, got {max_hops}")

    # Load full relationship adjacency list (bounded — production should cap)
    stmt = select(Relationship)
    rows = (await session.execute(stmt)).scalars().all()

    # Build adjacency: node_id → list[(neighbour_id, rel)]
    from collections import deque
    adj: dict[str, list[tuple[str, object]]] = defaultdict(list)
    for r in rows:
        a, b = str(r.person_a_id), str(r.person_b_id)
        adj[a].append((b, r))
        adj[b].append((a, r))

    # BFS
    start, end = from_id, to_id
    if start == end:
        return {"path": [start], "edges": []}

    visited: set[str] = {start}
    # Queue items: (current_node, path_so_far, edges_so_far)
    queue: deque[tuple[str, list[str], list[dict]]] = deque()
    queue.append((start, [start], []))

    while queue:
        current, path, path_edges = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for neighbour, rel in adj[current]:
            if neighbour in visited:
                continue
            new_path = path + [neighbour]
            new_edges = path_edges + [
                _edge(current, neighbour, rel.rel_type, rel.score or 0.5)
            ]
            if neighbour == end:
                return {"path": new_path, "edges": new_edges}
            visited.add(neighbour)
            queue.append((neighbour, new_path, new_edges))

    return {"path": None, "reason": "no_path_within_max_hops"}
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "find_shortest_path" -v`

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/graph/entity_graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: add EntityGraphBuilder.find_shortest_path() BFS with max_hops cap and entity_types filter"
```

---

### Task 4: EntityGraphBuilder.expand_entity()

**Files:**
- Modify: `modules/graph/entity_graph.py`
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_graph_endpoints.py`:

```python
# ── Task 4: expand_entity ─────────────────────────────────────────────────────


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

    # execute calls in expand_entity:
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


async def test_expand_entity_unknown_type_raises():
    session = AsyncMock()
    builder = EntityGraphBuilder()
    with pytest.raises(ValueError, match="Unsupported entity_type"):
        await builder.expand_entity("crypto_wallet", str(uuid.uuid4()), session)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "expand_entity" -v`

Expected: FAIL with `AttributeError: 'EntityGraphBuilder' object has no attribute 'expand_entity'`

- [ ] **Step 3: Write minimal implementation**

Add to `EntityGraphBuilder`:

```python
async def expand_entity(
    self,
    entity_type: str,
    entity_id: str,
    session: AsyncSession,
) -> dict:
    """
    Return 1-hop graph expansion for any entity type.

    For person nodes: runs build_person_graph at depth=1.
    Other entity types are not yet traversable as graph roots (stub returns
    the single node with no neighbours — raises ValueError for unknown types).
    """
    supported = {"person", "company", "address", "email", "phone", "domain", "ip", "wallet"}
    if entity_type not in supported:
        raise ValueError(f"Unsupported entity_type: {entity_type!r}")

    if entity_type == "person":
        return await self.build_person_graph(entity_id, session, depth=1)

    # Non-person entity: return the stub node only (no traversal model yet)
    return {
        "nodes": [_stub_node(f"{entity_type}:{entity_id}", entity_type, entity_id)],
        "edges": [],
    }
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "expand_entity" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/graph/entity_graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: add EntityGraphBuilder.expand_entity() with 1-hop person expansion"
```

---

### Task 5: Extend existing person network endpoint to include non-person entity nodes

**Files:**
- Modify: `modules/graph/entity_graph.py` (no change — `build_person_graph` already emits address/company/phone/email nodes)
- Modify: `api/routes/graph.py` (fix response to expose `node_count` / `edge_count`)
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_graph_endpoints.py`:

```python
# ── Task 5: person network includes non-person entity nodes ───────────────────


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "person_network_response_has_node_and_edge_count" -v`

Expected: FAIL with `KeyError: 'node_count'`

- [ ] **Step 3: Write minimal implementation**

In `api/routes/graph.py`, update the `person_network` handler response to expose counts:

```python
# Replace the return block inside person_network():
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    return {
        "person_id": person_id,
        "depth": depth,
        "nodes": _serialize(nodes),
        "edges": _serialize(edges),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "includes_address_and_company or node_and_edge_count" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: expose node_count/edge_count in person network response; confirm multi-entity node inclusion"
```

---

### Task 6: API endpoints — GET /graph/nodes and GET /graph/edges

**Files:**
- Modify: `api/routes/graph.py`
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_graph_endpoints.py`:

```python
# ── Task 6: GET /graph/nodes, GET /graph/edges ───────────────────────────────


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "graph_nodes_endpoint or graph_edges_endpoint" -v`

Expected: FAIL with `ImportError: cannot import name 'graph_nodes'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/routes/graph.py`:

```python
@router.get("/nodes")
async def graph_nodes(
    limit: int = Query(500, ge=1, le=500, description="Max nodes per page"),
    offset: int = Query(0, ge=0),
    entity_types: str | None = Query(
        None, description="Comma-separated entity types: person,company,address,phone,email"
    ),
    session: AsyncSession = DbDep,
):
    """Paginated list of graph nodes, ordered by degree (risk_score desc for persons)."""
    types = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        nodes = await _graph_builder.get_nodes_paginated(
            session, limit=limit, offset=offset, entity_types=types
        )
    except Exception as exc:
        logger.exception("graph_nodes failed")
        raise HTTPException(500, "Internal error") from exc
    return {"nodes": _serialize(nodes), "count": len(nodes), "offset": offset}


@router.get("/edges")
async def graph_edges(
    limit: int = Query(1000, ge=1, le=2000, description="Max edges per page"),
    offset: int = Query(0, ge=0),
    session: AsyncSession = DbDep,
):
    """Paginated list of relationship edges."""
    try:
        edges = await _graph_builder.get_edges_paginated(
            session, limit=limit, offset=offset
        )
    except Exception as exc:
        logger.exception("graph_edges failed")
        raise HTTPException(500, "Internal error") from exc
    return {"edges": _serialize(edges), "count": len(edges), "offset": offset}
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "graph_nodes_endpoint or graph_edges_endpoint" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: add GET /graph/nodes and GET /graph/edges paginated API endpoints"
```

---

### Task 7: API endpoints — GET /graph/path and GET /graph/entity/{type}/{id}/expand

**Files:**
- Modify: `api/routes/graph.py`
- Test: `tests/test_api/test_graph_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_api/test_graph_endpoints.py`:

```python
# ── Task 7: GET /graph/path, GET /graph/entity/{type}/{id}/expand ─────────────


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "graph_path_endpoint or graph_expand_endpoint" -v`

Expected: FAIL with `ImportError: cannot import name 'graph_path'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/routes/graph.py`:

```python
@router.get("/path")
async def graph_path(
    from_id: str = Query(..., description="Source node ID"),
    to_id: str = Query(..., description="Target node ID"),
    entity_types: str | None = Query(
        None, description="Comma-separated traversal filter: person,company"
    ),
    max_hops: int = Query(6, ge=1, description="Maximum hops; hard cap is 10"),
    session: AsyncSession = DbDep,
):
    """BFS shortest path between two nodes with optional entity_type traversal filter."""
    if max_hops > 10:
        raise HTTPException(400, "max_hops must be ≤ 10")
    types = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        result = await _graph_builder.find_shortest_path(
            from_id, to_id, session, entity_types=types, max_hops=max_hops
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("graph_path failed from=%s to=%s", from_id, to_id)
        raise HTTPException(500, "Internal error") from exc
    return result


@router.get("/entity/{entity_type}/{entity_id}/expand")
async def graph_expand(
    entity_type: str,
    entity_id: str,
    session: AsyncSession = DbDep,
):
    """Return 1-hop expansion for any entity node."""
    try:
        result = await _graph_builder.expand_entity(entity_type, entity_id, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("graph_expand failed type=%s id=%s", entity_type, entity_id)
        raise HTTPException(500, "Internal error") from exc
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "nodes": _serialize(result.get("nodes", [])),
        "edges": _serialize(result.get("edges", [])),
    }
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_graph_endpoints.py -k "graph_path_endpoint or graph_expand_endpoint" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/graph.py tests/test_api/test_graph_endpoints.py
git commit -m "feat: add GET /graph/path BFS endpoint and GET /graph/entity/{type}/{id}/expand"
```

---

### Task 8: Web Worker for D3 force simulation (graph_worker.js)

**Files:**
- Create: `static/graph_worker.js`

No unit test for the Worker itself (it requires a browser runtime). Verification is visual in Task 9.

- [ ] **Step 1: Write the Web Worker file**

Create `/home/wolf/Lycan-Data/static/graph_worker.js`:

```javascript
/**
 * graph_worker.js — D3 v7 force simulation running off the main thread.
 *
 * Messages IN  (from main thread):
 *   { type: 'init',   nodes: [...], edges: [...], width: N, height: N }
 *   { type: 'tick' }   — not used; worker auto-ticks and posts results
 *   { type: 'pin',    nodeId: '...', x: N, y: N }
 *   { type: 'unpin',  nodeId: '...' }
 *   { type: 'resize', width: N, height: N }
 *   { type: 'stop' }
 *
 * Messages OUT (to main thread):
 *   { type: 'tick',   nodes: [{id, x, y, vx, vy, fx, fy}], edges: [...] }
 *   { type: 'end' }
 */

importScripts('https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js');

let simulation = null;
let _nodes = [];
let _edges = [];

function buildSimulation(nodes, edges, width, height) {
  // Deep-copy so D3 can mutate freely
  _nodes = nodes.map(n => Object.assign({}, n));
  _edges = edges.map(e => Object.assign({}, e));

  if (simulation) simulation.stop();

  simulation = d3.forceSimulation(_nodes)
    .force('link', d3.forceLink(_edges)
      .id(d => d.id)
      .distance(d => 80 + (1 - (d.confidence || 0.5)) * 40)
      .strength(0.4)
    )
    .force('charge', d3.forceManyBody().strength(-300).distanceMax(400))
    .force('center', d3.forceCenter(width / 2, height / 2).strength(0.08))
    .force('collide', d3.forceCollide().radius(28).strength(0.7))
    .alphaDecay(0.028)
    .velocityDecay(0.4)
    .on('tick', () => {
      // Send positions to main thread every tick
      self.postMessage({
        type: 'tick',
        nodes: _nodes.map(n => ({
          id: n.id, x: n.x, y: n.y,
          vx: n.vx, vy: n.vy, fx: n.fx, fy: n.fy
        })),
        edges: _edges.map(e => ({
          source: typeof e.source === 'object' ? e.source.id : e.source,
          target: typeof e.target === 'object' ? e.target.id : e.target,
          type:   e.type,
          confidence: e.confidence
        }))
      });
    })
    .on('end', () => {
      self.postMessage({ type: 'end' });
    });
}

self.onmessage = function(evt) {
  const msg = evt.data;
  switch (msg.type) {
    case 'init':
      buildSimulation(msg.nodes, msg.edges, msg.width, msg.height);
      break;

    case 'pin': {
      const n = _nodes.find(x => x.id === msg.nodeId);
      if (n) { n.fx = msg.x; n.fy = msg.y; }
      if (simulation) simulation.alpha(0.1).restart();
      break;
    }

    case 'unpin': {
      const n = _nodes.find(x => x.id === msg.nodeId);
      if (n) { n.fx = null; n.fy = null; }
      if (simulation) simulation.alpha(0.1).restart();
      break;
    }

    case 'resize':
      if (simulation) {
        simulation.force('center', d3.forceCenter(msg.width / 2, msg.height / 2).strength(0.08));
        simulation.alpha(0.1).restart();
      }
      break;

    case 'stop':
      if (simulation) simulation.stop();
      break;

    default:
      break;
  }
};
```

- [ ] **Step 2: Verify file was created**

Run: `ls -lh /home/wolf/Lycan-Data/static/graph_worker.js`

Expected: file exists, ~2 KB

- [ ] **Step 3: Commit**

```bash
git add static/graph_worker.js
git commit -m "feat: add graph_worker.js — D3 v7 force simulation in Web Worker"
```

---

### Task 9: D3 SVG graph renderer in index.html — node shapes, edge rendering, interactions

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Identify the insertion point**

The entire `renderGraph()` method body (lines ~2157–2310) is replaced. The existing company search, person network, and fraud ring sections remain as separate cards below the D3 canvas. The D3 canvas goes at the top of `renderGraph()` as the primary view.

- [ ] **Step 2: Add D3 CDN script tag in `<head>`**

Find the `<head>` block in `static/index.html` and add before the closing `</head>` tag:

```html
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
```

- [ ] **Step 3: Replace renderGraph() body with D3 implementation**

Replace from `async renderGraph() {` through the closing `}` that ends the method (before the next method). The new body:

```javascript
  async renderGraph() {
    this.root.textContent = '';

    const hdr = div('page-header');
    const left = div('');
    left.append(div('page-title','Knowledge Graph'), div('page-sub','Force-directed entity graph · 8 types · BFS path finder'));
    hdr.appendChild(left);
    this.root.appendChild(hdr);

    // ── Main layout: filter sidebar + SVG canvas ──────────────────────────
    const layout = div('');
    layout.style.cssText = 'display:flex;gap:16px;align-items:flex-start;';
    this.root.appendChild(layout);

    // ── Filter panel ──────────────────────────────────────────────────────
    const filterPanel = div('card');
    filterPanel.style.cssText = 'min-width:210px;max-width:210px;flex-shrink:0;';
    const fpHdr = div('card-header'); fpHdr.appendChild(span('card-title','Filters'));
    const fpBody = div('card-body');
    fpBody.style.cssText = 'display:flex;flex-direction:column;gap:10px;';

    // Entity type checkboxes
    const entityTypes = [
      {key:'person',  label:'Person'},
      {key:'company', label:'Company'},
      {key:'address', label:'Location'},
      {key:'email',   label:'Email'},
      {key:'phone',   label:'Phone'},
      {key:'wallet',  label:'Wallet'},
      {key:'domain',  label:'Domain'},
    ];
    const entityChecks = {};
    const etGroup = div('');
    const etLabel = div(''); etLabel.style.cssText='font-size:10px;font-weight:600;color:var(--text-mute);letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;';
    etLabel.textContent = 'Entity Types';
    etGroup.appendChild(etLabel);
    entityTypes.forEach(({key,label}) => {
      const row = div(''); row.style.cssText='display:flex;align-items:center;gap:6px;margin:2px 0;';
      const cb = el('input',''); cb.type='checkbox'; cb.checked=true; cb.id='et_'+key;
      const lbl = el('label',''); lbl.htmlFor='et_'+key; lbl.textContent=label;
      lbl.style.cssText='font-size:12px;cursor:pointer;color:var(--text);';
      entityChecks[key] = cb;
      row.append(cb, lbl);
      etGroup.appendChild(row);
    });
    fpBody.appendChild(etGroup);

    // Rel type checkboxes
    const relTypes = [
      {key:'social',            label:'Social'},
      {key:'financial',         label:'Financial'},
      {key:'geographic',        label:'Geographic'},
      {key:'criminal',          label:'Criminal'},
      {key:'shared-identifier', label:'Shared ID'},
    ];
    const relChecks = {};
    const rtGroup = div('');
    const rtLabel = div(''); rtLabel.style.cssText='font-size:10px;font-weight:600;color:var(--text-mute);letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;margin-top:4px;';
    rtLabel.textContent = 'Relationship Types';
    rtGroup.appendChild(rtLabel);
    relTypes.forEach(({key,label}) => {
      const row = div(''); row.style.cssText='display:flex;align-items:center;gap:6px;margin:2px 0;';
      const cb = el('input',''); cb.type='checkbox'; cb.checked=true; cb.id='rt_'+key;
      const lbl = el('label',''); lbl.htmlFor='rt_'+key; lbl.textContent=label;
      lbl.style.cssText='font-size:12px;cursor:pointer;color:var(--text);';
      relChecks[key] = cb;
      row.append(cb, lbl);
      rtGroup.appendChild(row);
    });
    fpBody.appendChild(rtGroup);

    // Min score slider
    const scoreGroup = div('');
    const scoreLabel = div(''); scoreLabel.style.cssText='font-size:10px;font-weight:600;color:var(--text-mute);letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;margin-top:4px;';
    scoreLabel.textContent = 'Min Edge Score';
    const scoreVal = span('','0.0');
    scoreVal.style.cssText='font-size:11px;color:var(--text-dim);margin-left:6px;';
    const scoreSlider = el('input',''); scoreSlider.type='range'; scoreSlider.min=0; scoreSlider.max=1; scoreSlider.step=0.05; scoreSlider.value=0;
    scoreSlider.style.cssText='width:100%;margin-top:4px;';
    scoreSlider.addEventListener('input', () => { scoreVal.textContent = parseFloat(scoreSlider.value).toFixed(2); applyFilters(); });
    scoreGroup.append(scoreLabel, scoreVal, scoreSlider);
    fpBody.appendChild(scoreGroup);

    // Text search
    const searchGroup = div('');
    const searchLabel = div(''); searchLabel.style.cssText='font-size:10px;font-weight:600;color:var(--text-mute);letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;margin-top:4px;';
    searchLabel.textContent = 'Search Label';
    const searchInp = el('input','filter-input'); searchInp.placeholder='Filter by name…'; searchInp.style.cssText='width:100%;';
    searchInp.addEventListener('input', applyFilters);
    searchGroup.append(searchLabel, searchInp);
    fpBody.appendChild(searchGroup);

    // Load graph button
    const loadBtn = el('button','btn primary','Load Graph');
    loadBtn.style.cssText='width:100%;margin-top:8px;';
    fpBody.appendChild(loadBtn);

    filterPanel.append(fpHdr, fpBody);
    layout.appendChild(filterPanel);

    // ── SVG canvas ────────────────────────────────────────────────────────
    const canvasWrap = div('card');
    canvasWrap.style.cssText = 'flex:1;min-height:600px;position:relative;overflow:hidden;';
    layout.appendChild(canvasWrap);

    const svgEl = document.createElementNS('http://www.w3.org/2000/svg','svg');
    svgEl.style.cssText = 'width:100%;height:600px;background:var(--bg2);border-radius:var(--radius);display:block;';
    canvasWrap.appendChild(svgEl);

    // Node side panel
    const sidePanel = div('card');
    sidePanel.style.cssText = 'position:absolute;right:12px;top:12px;width:200px;display:none;z-index:10;';
    const sidePanelBody = div('card-body');
    sidePanel.appendChild(sidePanelBody);
    canvasWrap.appendChild(sidePanel);

    // Context menu
    const ctxMenu = div('');
    ctxMenu.style.cssText = 'position:fixed;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:4px 0;display:none;z-index:100;min-width:140px;box-shadow:0 4px 16px rgba(0,0,0,0.5);';
    document.body.appendChild(ctxMenu);
    const ctxItems = [
      {label:'Expand 1 hop',   action:'expand'},
      {label:'Hide node',      action:'hide'},
      {label:'Focus',          action:'focus'},
      {label:'Find path to…',  action:'path'},
    ];
    ctxItems.forEach(({label,action}) => {
      const item = div(''); item.textContent = label;
      item.style.cssText='padding:7px 14px;font-size:12px;cursor:pointer;color:var(--text);transition:background .1s;';
      item.dataset.action = action;
      item.addEventListener('mouseenter', () => { item.style.background='var(--bg2)'; });
      item.addEventListener('mouseleave', () => { item.style.background=''; });
      ctxMenu.appendChild(item);
    });
    document.addEventListener('click', () => { ctxMenu.style.display='none'; }, {capture:true});

    // ── D3 state ──────────────────────────────────────────────────────────
    const ENTITY_COLORS = {
      person:  '#1a6ef5',
      company: '#805ad5',
      address: '#d69e2e',
      email:   '#00c48c',
      phone:   '#38b2ac',
      wallet:  '#e53e3e',
      domain:  '#ed8936',
      ip:      '#718096',
    };
    const EDGE_COLORS = {
      social:            '#1a6ef5',
      financial:         '#00c48c',
      geographic:        '#d69e2e',
      criminal:          '#e53e3e',
      'shared-identifier': '#384a5c',
    };

    let allNodes = [], allEdges = [];
    let visibleNodes = [], visibleEdges = [];
    let pathNodeIds = new Set();
    let shiftFirst = null;
    let hiddenNodeIds = new Set();
    let ctxTarget = null;
    let worker = null;

    const svg = d3.select(svgEl);
    const svgW = () => svgEl.getBoundingClientRect().width || 900;
    const svgH = () => svgEl.getBoundingClientRect().height || 600;

    // Zoom/pan
    const rootG = svg.append('g');
    const zoom = d3.zoom().scaleExtent([0.05, 5]).on('zoom', (evt) => {
      rootG.attr('transform', evt.transform);
    });
    svg.call(zoom);

    // Layers
    const edgeLayer = rootG.append('g').attr('class','edges');
    const nodeLayer = rootG.append('g').attr('class','nodes');

    // ── Shape drawing ──────────────────────────────────────────────────────
    function drawShape(sel) {
      sel.each(function(d) {
        const g = d3.select(this);
        g.selectAll('*').remove();
        const col = ENTITY_COLORS[d.type] || '#718096';
        switch(d.type) {
          case 'person':
            g.append('circle').attr('r',18).attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          case 'company':
            g.append('rect').attr('x',-14).attr('y',-14).attr('width',28).attr('height',28)
             .attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          case 'address': {
            // Diamond: rotated square
            const s = 18;
            g.append('polygon')
             .attr('points', `0,${-s} ${s},0 0,${s} ${-s},0`)
             .attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          }
          case 'email': {
            // Triangle (upward)
            const h = 20;
            g.append('polygon')
             .attr('points', `0,${-h} ${h*0.866},${h*0.5} ${-h*0.866},${h*0.5}`)
             .attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          }
          case 'phone': {
            // Hexagon
            const r = 16;
            const pts = d3.range(6).map(i => {
              const a = (Math.PI/3)*i - Math.PI/6;
              return `${r*Math.cos(a)},${r*Math.sin(a)}`;
            }).join(' ');
            g.append('polygon').attr('points',pts)
             .attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          }
          case 'wallet': {
            // Star (5-pointed)
            const ro=16, ri=7;
            const pts = d3.range(10).map(i => {
              const a = (Math.PI/5)*i - Math.PI/2;
              const r2 = i%2===0 ? ro : ri;
              return `${r2*Math.cos(a)},${r2*Math.sin(a)}`;
            }).join(' ');
            g.append('polygon').attr('points',pts)
             .attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          }
          case 'domain': {
            // Octagon
            const r2 = 15;
            const pts2 = d3.range(8).map(i => {
              const a = (Math.PI/4)*i - Math.PI/8;
              return `${r2*Math.cos(a)},${r2*Math.sin(a)}`;
            }).join(' ');
            g.append('polygon').attr('points',pts2)
             .attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
          }
          case 'ip':
          default:
            g.append('circle').attr('r',10).attr('fill',col).attr('stroke','#0a0e14').attr('stroke-width',2);
            break;
        }
        // Label
        g.append('text')
         .attr('y', 26).attr('text-anchor','middle')
         .attr('font-size','10px').attr('fill','#8fa3b8')
         .attr('pointer-events','none')
         .text(d.label ? d.label.slice(0,18) : d.id.slice(0,12));
      });
    }

    // ── Filter logic ──────────────────────────────────────────────────────
    function applyFilters() {
      const enabledTypes = new Set(Object.entries(entityChecks).filter(([,cb])=>cb.checked).map(([k])=>k));
      const enabledRels  = new Set(Object.entries(relChecks).filter(([,cb])=>cb.checked).map(([k])=>k));
      const minScore = parseFloat(scoreSlider.value);
      const query = searchInp.value.trim().toLowerCase();

      visibleNodes = allNodes.filter(n =>
        !hiddenNodeIds.has(n.id) &&
        enabledTypes.has(n.type) &&
        (!query || (n.label||'').toLowerCase().includes(query))
      );
      const visNodeIds = new Set(visibleNodes.map(n=>n.id));
      visibleEdges = allEdges.filter(e => {
        const src = typeof e.source==='object' ? e.source.id : e.source;
        const tgt = typeof e.target==='object' ? e.target.id : e.target;
        if (!visNodeIds.has(src) || !visNodeIds.has(tgt)) return false;
        const relKey = Object.keys(EDGE_COLORS).find(k => (e.type||'').toLowerCase().includes(k)) || 'social';
        if (!enabledRels.has(relKey) && !enabledRels.has(e.type)) return false;
        return (e.confidence || 0.5) >= minScore;
      });
      renderD3();
    }

    // ── D3 render ─────────────────────────────────────────────────────────
    function renderD3() {
      // Edges
      const eSel = edgeLayer.selectAll('line.edge').data(visibleEdges, e => {
        const s = typeof e.source==='object'?e.source.id:e.source;
        const t = typeof e.target==='object'?e.target.id:e.target;
        return s+'_'+t+'_'+e.type;
      });
      eSel.join(
        enter => enter.append('line').attr('class','edge')
          .attr('stroke', e => {
            if (pathNodeIds.size) {
              const s = typeof e.source==='object'?e.source.id:e.source;
              const t = typeof e.target==='object'?e.target.id:e.target;
              return (pathNodeIds.has(s)&&pathNodeIds.has(t)) ? '#f6c90e' : '#1e2a38';
            }
            const k = Object.keys(EDGE_COLORS).find(k2=>(e.type||'').toLowerCase().includes(k2));
            return EDGE_COLORS[k] || '#253040';
          })
          .attr('stroke-width', e => Math.max(0.5, (e.confidence||0.5)*2.5))
          .attr('opacity', 0.6),
        update => update
          .attr('stroke', e => {
            if (pathNodeIds.size) {
              const s = typeof e.source==='object'?e.source.id:e.source;
              const t = typeof e.target==='object'?e.target.id:e.target;
              return (pathNodeIds.has(s)&&pathNodeIds.has(t)) ? '#f6c90e' : '#1e2a38';
            }
            const k = Object.keys(EDGE_COLORS).find(k2=>(e.type||'').toLowerCase().includes(k2));
            return EDGE_COLORS[k] || '#253040';
          })
          .attr('stroke-width', e => Math.max(0.5, (e.confidence||0.5)*2.5)),
        exit => exit.remove()
      );

      // Nodes
      const nSel = nodeLayer.selectAll('g.node').data(visibleNodes, n => n.id);
      nSel.join(
        enter => {
          const g = enter.append('g').attr('class','node').style('cursor','pointer');
          g.call(drawShape);
          g.call(d3.drag()
            .on('start', (evt, d) => {
              if (worker) worker.postMessage({type:'pin', nodeId:d.id, x:evt.x, y:evt.y});
            })
            .on('drag', (evt, d) => {
              d.fx = evt.x; d.fy = evt.y;
              d3.select(this).attr('transform',`translate(${evt.x},${evt.y})`);
              if (worker) worker.postMessage({type:'pin', nodeId:d.id, x:evt.x, y:evt.y});
            })
            .on('end', (_evt, d) => {
              // pin stays on release (drag = pin)
            })
          );
          g.on('click', (evt, d) => {
            if (evt.shiftKey) {
              handleShiftClick(d);
            } else {
              showSidePanel(d);
            }
          });
          g.on('dblclick', (evt, d) => {
            evt.stopPropagation();
            handleExpand(d);
          });
          g.on('contextmenu', (evt, d) => {
            evt.preventDefault();
            ctxTarget = d;
            ctxMenu.style.left = evt.clientX+'px';
            ctxMenu.style.top  = evt.clientY+'px';
            ctxMenu.style.display = 'block';
          });
          return g;
        },
        update => update.call(drawShape),
        exit => exit.remove()
      );

      // Path highlight dim
      nodeLayer.selectAll('g.node').style('opacity', n => {
        if (!pathNodeIds.size) return 1;
        return pathNodeIds.has(n.id) ? 1 : 0.15;
      });
    }

    // ── Worker tick → update positions ────────────────────────────────────
    function applyTick(tickNodes) {
      const posMap = {};
      tickNodes.forEach(n => { posMap[n.id] = n; });
      nodeLayer.selectAll('g.node').attr('transform', d => {
        const p = posMap[d.id];
        if (p) { d.x = p.x; d.y = p.y; }
        return `translate(${d.x||0},${d.y||0})`;
      });
      edgeLayer.selectAll('line.edge')
        .attr('x1', e => (typeof e.source==='object' ? e.source : allNodes.find(n=>n.id===e.source) || {x:0}).x || 0)
        .attr('y1', e => (typeof e.source==='object' ? e.source : allNodes.find(n=>n.id===e.source) || {y:0}).y || 0)
        .attr('x2', e => (typeof e.target==='object' ? e.target : allNodes.find(n=>n.id===e.target) || {x:0}).x || 0)
        .attr('y2', e => (typeof e.target==='object' ? e.target : allNodes.find(n=>n.id===e.target) || {y:0}).y || 0);
    }

    // ── Side panel ────────────────────────────────────────────────────────
    function showSidePanel(d) {
      sidePanelBody.textContent = '';
      const title = div(''); title.style.cssText='font-weight:600;font-size:13px;color:var(--text);margin-bottom:6px;';
      title.textContent = d.label || d.id;
      const typeBadge = span('tag muted', (d.type||'?').toUpperCase());
      const risk = div(''); risk.style.cssText='font-size:11px;color:var(--text-dim);margin-top:4px;';
      risk.textContent = 'Risk: '+(d.risk_score!=null ? Math.round(d.risk_score*100)+'%' : '—');
      const openBtn = el('button','btn','Open full card');
      openBtn.style.cssText='width:100%;margin-top:8px;font-size:11px;';
      openBtn.addEventListener('click', () => {
        if (d.type==='person') window.location.hash='#/profile/'+d.id;
      });
      sidePanelBody.append(title, typeBadge, risk, openBtn);
      sidePanel.style.display = 'block';
    }

    // ── Context menu actions ───────────────────────────────────────────────
    ctxMenu.querySelectorAll('[data-action]').forEach(item => {
      item.addEventListener('click', async () => {
        if (!ctxTarget) return;
        const action = item.dataset.action;
        ctxMenu.style.display='none';
        if (action==='expand') await handleExpand(ctxTarget);
        if (action==='hide') { hiddenNodeIds.add(ctxTarget.id); applyFilters(); }
        if (action==='focus') {
          // Reset hidden, keep only this node and its 1-hop
          const adj = new Set([ctxTarget.id]);
          allEdges.forEach(e => {
            const s=typeof e.source==='object'?e.source.id:e.source;
            const t=typeof e.target==='object'?e.target.id:e.target;
            if (s===ctxTarget.id) adj.add(t);
            if (t===ctxTarget.id) adj.add(s);
          });
          hiddenNodeIds = new Set(allNodes.map(n=>n.id).filter(id=>!adj.has(id)));
          applyFilters();
        }
        if (action==='path') {
          shiftFirst = ctxTarget;
          sidePanelBody.textContent='';
          const hint=div(''); hint.style.cssText='font-size:11px;color:var(--yellow);';
          hint.textContent='Now Shift+click a second node to find path';
          sidePanelBody.appendChild(hint);
          sidePanel.style.display='block';
        }
      });
    });

    // ── Shift+click shortest path ─────────────────────────────────────────
    async function handleShiftClick(d) {
      if (!shiftFirst) {
        shiftFirst = d;
        pathNodeIds.clear();
        renderD3();
        return;
      }
      if (shiftFirst.id === d.id) { shiftFirst=null; return; }
      try {
        const from = shiftFirst.id;
        const to   = d.id;
        shiftFirst = null;
        const result = await apiGet(`/graph/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&max_hops=6`);
        if (result.path) {
          pathNodeIds = new Set(result.path);
          renderD3();
          // Show summary
          sidePanelBody.textContent='';
          const info=div(''); info.style.cssText='font-size:12px;color:var(--green);margin-bottom:6px;';
          info.textContent=`Path: ${result.path.length} nodes`;
          const clearBtn=el('button','btn','Clear path'); clearBtn.style.cssText='width:100%;font-size:11px;';
          clearBtn.addEventListener('click',()=>{ pathNodeIds.clear(); renderD3(); sidePanel.style.display='none'; });
          sidePanelBody.append(info,clearBtn);
          sidePanel.style.display='block';
        } else {
          sidePanelBody.textContent='';
          const msg=div(''); msg.style.cssText='font-size:12px;color:var(--red);';
          msg.textContent='No path found within 6 hops';
          sidePanelBody.appendChild(msg);
          sidePanel.style.display='block';
        }
      } catch(e) { console.error('path find failed',e); }
    }

    // ── Double-click expand ────────────────────────────────────────────────
    async function handleExpand(d) {
      try {
        const res = await apiGet(`/graph/entity/${d.type}/${encodeURIComponent(d.id.replace(/^[^:]+:/,''))}/expand`);
        const newNodes = res.nodes||[];
        const newEdges = res.edges||[];
        const existingIds = new Set(allNodes.map(n=>n.id));
        newNodes.forEach(n => { if (!existingIds.has(n.id)) allNodes.push(n); });
        newEdges.forEach(e => allEdges.push(e));
        if (worker) {
          worker.postMessage({type:'init', nodes:allNodes, edges:allEdges, width:svgW(), height:svgH()});
        }
        applyFilters();
      } catch(e) { console.error('expand failed',e); }
    }

    // ── Load initial graph ─────────────────────────────────────────────────
    async function loadGraph() {
      loadBtn.disabled=true; loadBtn.textContent='Loading…';
      try {
        const [nd, ed] = await Promise.all([
          apiGet('/graph/nodes?limit=500&offset=0&entity_types=person,company,address,email,phone'),
          apiGet('/graph/edges?limit=1000&offset=0'),
        ]);
        allNodes = nd.nodes||[];
        allEdges = ed.edges||[];

        // Assign initial random positions
        const w = svgW(), h = svgH();
        allNodes.forEach(n => { n.x = Math.random()*w; n.y = Math.random()*h; });

        // Start Web Worker
        if (worker) worker.terminate();
        worker = new Worker('/static/graph_worker.js');
        worker.onmessage = (evt) => {
          if (evt.data.type==='tick') applyTick(evt.data.nodes);
        };
        worker.postMessage({type:'init', nodes:allNodes, edges:allEdges, width:w, height:h});

        applyFilters();

        // "Load more" button
        if ((nd.nodes||[]).length===500) {
          const moreBtn=el('button','btn','Load next 500 nodes');
          moreBtn.style.cssText='margin-top:10px;width:100%;';
          moreBtn.addEventListener('click', async () => {
            moreBtn.disabled=true;
            const nd2 = await apiGet(`/graph/nodes?limit=500&offset=${allNodes.length}&entity_types=person,company,address,email,phone`);
            const existing=new Set(allNodes.map(n=>n.id));
            (nd2.nodes||[]).forEach(n=>{ if(!existing.has(n.id)) allNodes.push(n); });
            worker.postMessage({type:'init', nodes:allNodes, edges:allEdges, width:svgW(), height:svgH()});
            applyFilters();
            if ((nd2.nodes||[]).length < 500) moreBtn.remove();
            else moreBtn.disabled=false;
          });
          canvasWrap.appendChild(moreBtn);
        }
      } catch(e) {
        canvasWrap.appendChild(span('red-txt','Failed to load graph: '+e.message));
      } finally {
        loadBtn.disabled=false; loadBtn.textContent='Reload Graph';
      }
    }

    // Wire entity/rel checkboxes to live filter
    Object.values(entityChecks).forEach(cb => cb.addEventListener('change', applyFilters));
    Object.values(relChecks).forEach(cb => cb.addEventListener('change', applyFilters));
    loadBtn.addEventListener('click', loadGraph);

    // ── Existing tool sections (company search, fraud rings) below graph ───
    this.root.appendChild(div('',''));  // spacer
    // (Company Search, Person Network, Fraud Ring Detection cards preserved below)
    this._renderGraphLegacyCards();
  }

  _renderGraphLegacyCards() {
    // ── Section: Company Search ──────────────────────────────────────────
    const coCard = div('card'); coCard.style.marginTop='16px';
    const coHdr = div('card-header'); coHdr.appendChild(span('card-title','⬡ Company Search'));
    const coBody = div('card-body');
    const coBar = div('filter-bar');
    const coNameInp = el('input','filter-input'); coNameInp.placeholder='Company name…'; coNameInp.style.minWidth='220px';
    const coStateInp = el('input','filter-input'); coStateInp.placeholder='State (optional)…'; coStateInp.style.minWidth='140px';
    const coBtn = el('button','btn primary','Search');
    coBar.append(coNameInp, coStateInp, coBtn);
    const coResults = div(''); coResults.style.marginTop='12px';
    coBody.append(coBar, coResults);
    coCard.append(coHdr, coBody);
    this.root.appendChild(coCard);

    const doCoSearch = async () => {
      const name = coNameInp.value.trim(); if (!name) return;
      coBtn.disabled=true; coBtn.textContent='Searching…';
      coResults.textContent=''; coResults.appendChild(span('spinner'));
      try {
        const d = await apiGet('/graph/company/search?name='+encodeURIComponent(name)+(coStateInp.value.trim()?'&state='+encodeURIComponent(coStateInp.value.trim()):''));
        coResults.textContent='';
        if (!d.companies || d.companies.length===0) { coResults.appendChild(div('dim','No companies found')); return; }
        d.companies.forEach(c => {
          const card2=div('card'); card2.style.marginBottom='10px';
          const body2=div('card-body');
          const titleRow=div(''); titleRow.style.cssText='display:flex;align-items:center;gap:10px;margin-bottom:8px';
          const nm=div('page-title'); nm.style.fontSize='14px'; nm.textContent=c.legal_name||'—';
          const stBadge=span('status-pill '+(c.status==='ACTIVE'?'done':'failed'),(c.status||'—').toUpperCase());
          titleRow.append(nm,stBadge);
          const kv=div('kv-grid');
          [['State',c.state||'—'],['Confidence',Math.round((c.confidence||0)*100)+'%'],['Officers',(c.officer_count||0)+' officers']].forEach(([k,v])=>{
            const row2=div('kv-row'); row2.append(span('kv-key',k),span('kv-val',v)); kv.appendChild(row2);
          });
          body2.append(titleRow,kv); card2.appendChild(body2); coResults.appendChild(card2);
        });
      } catch(e) { coResults.textContent=''; coResults.appendChild(span('red-txt','Failed: '+e.message)); }
      finally { coBtn.disabled=false; coBtn.textContent='Search'; }
    };
    coBtn.addEventListener('click', doCoSearch);
    coNameInp.addEventListener('keydown', e=>{ if(e.key==='Enter') doCoSearch(); });

    // ── Section: Fraud Ring Detection ────────────────────────────────────
    const frCard = div('card'); frCard.style.marginTop='16px';
    const frHdr = div('card-header'); frHdr.appendChild(span('card-title','⬡ Fraud Ring Detection'));
    const frBody = div('card-body');
    const frBar = div('filter-bar');
    const minConnSel = el('select','filter-sel');
    for (let i=2;i<=10;i++) { const o=el('option','',i+' min connections'); o.value=i; minConnSel.appendChild(o); }
    const frBtn = el('button','btn primary','Detect');
    frBar.append(span('filter-label','Min connections'), minConnSel, frBtn);
    const frResults = div(''); frResults.style.marginTop='12px';
    frBody.append(frBar, frResults);
    frCard.append(frHdr, frBody);
    this.root.appendChild(frCard);

    frBtn.addEventListener('click', async () => {
      frBtn.disabled=true; frBtn.textContent='Detecting…';
      frResults.textContent=''; frResults.appendChild(span('spinner'));
      try {
        const d = await apiPost('/graph/fraud-rings', {min_connections:parseInt(minConnSel.value,10)});
        frResults.textContent='';
        const rings=d.rings||d.fraud_rings||[];
        const meta=div(''); meta.style.cssText='font-size:12px;color:var(--text-dim);margin-bottom:12px';
        meta.textContent=rings.length+' ring'+(rings.length!==1?'s':'')+' detected';
        frResults.appendChild(meta);
        rings.forEach((ring,i)=>{
          const rc=div('card'); rc.style.marginBottom='10px';
          const rb=div('card-body');
          const rl=div(''); rl.style.cssText='font-size:11px;font-weight:600;color:var(--red);margin-bottom:6px;';
          rl.textContent='Ring '+(i+1)+' · '+(ring.persons||[]).length+' members';
          rb.appendChild(rl);
          rc.appendChild(rb);
          frResults.appendChild(rc);
        });
      } catch(e) { frResults.textContent=''; frResults.appendChild(span('red-txt','Failed: '+e.message)); }
      finally { frBtn.disabled=false; frBtn.textContent='Detect'; }
    });
  }
```

- [ ] **Step 4: Commit**

```bash
git add static/index.html
git commit -m "feat: replace renderGraph() with D3 v7 force-directed SVG graph — 8 entity types, shapes, edge colors, interactions"
```

---

### Task 10: Filter panel live filtering + Shift+click shortest path highlight

Filter panel and Shift+click are implemented inline in Task 9 (`applyFilters()` function and `handleShiftClick()`). This task covers smoke-testing and integration wiring.

**Files:**
- Modify: `static/index.html` (no additional code changes — just verify wiring)
- Test: `tests/test_api/test_graph_endpoints.py` (full suite run)

- [ ] **Step 1: Run the full new test file**

Run: `pytest tests/test_api/test_graph_endpoints.py -v`

Expected: All tests PASS

- [ ] **Step 2: Run the existing graph tests to confirm no regression**

Run: `pytest tests/test_graph/ -v`

Expected: All tests PASS

- [ ] **Step 3: Run full API test suite**

Run: `pytest tests/test_api/ -v`

Expected: All tests PASS

- [ ] **Step 4: Manual smoke test checklist**

Start the API server:
```bash
make api
```

Open browser at `http://localhost:8000`, navigate to Knowledge Graph:
- [ ] D3 SVG canvas renders without JS errors in console
- [ ] "Load Graph" button fetches `/graph/nodes` and `/graph/edges`, nodes appear as correct shapes
- [ ] Person node = blue circle, Company = purple square, Location = amber diamond, Email = green triangle, Phone = teal hexagon, Wallet = red star, Domain = orange octagon, IP = grey small circle
- [ ] Dragging a node pins it in place
- [ ] Clicking a node shows side panel with name, type badge, risk score, "Open full card" button
- [ ] Double-clicking a person node calls `/graph/entity/person/{id}/expand` and adds new nodes
- [ ] Right-clicking shows context menu with Expand, Hide, Focus, Find Path To
- [ ] Unchecking "Company" in filter panel immediately fades company nodes and orphaned edges
- [ ] Min Edge Score slider at 0.8 removes low-confidence edges in real time
- [ ] Shift+click node A, Shift+click node B → gold highlight path or "No path found" panel
- [ ] Entity type checkboxes filter correctly across all 7 types
- [ ] "Load next 500 nodes" button appears when first page is exactly 500 nodes
- [ ] `/graph/path?from=X&to=Y&max_hops=11` returns HTTP 400

- [ ] **Step 5: Commit**

```bash
git add static/index.html tests/test_api/test_graph_endpoints.py
git commit -m "feat: complete Phase 3 Knowledge Graph D3 — filter panel, Shift+click BFS path, full test suite"
```

---

## Implementation Notes

### BFS memory bound
`find_shortest_path()` loads the full `Relationship` table into memory for the adjacency list. For large datasets add a server-side `WHERE (person_a_id = $start OR person_b_id = $start OR ...)` pre-filter or a dedicated graph DB. The current implementation is correct for datasets up to ~100k edges.

### Web Worker compatibility
`graph_worker.js` uses `importScripts()` (classic Worker, not ESM). This is intentional — the D3 CDN build is a UMD bundle. If the project moves to a bundler (Vite/esbuild), switch to `import` syntax and an ESM Worker.

### Entity types not yet traversable as graph roots
`expand_entity()` returns a stub for `wallet`, `domain`, and `ip` types because those tables (`darkweb`, `web`, `identifier`) do not yet have a `degree` or adjacency index. Hook them up in a follow-on task once those tables have relationship rows.

### `distinct(EmploymentHistory.employer_name)` on PostgreSQL
`get_nodes_paginated()` uses `.distinct(EmploymentHistory.employer_name)` to deduplicate company nodes by name. This is PostgreSQL-specific (`DISTINCT ON`). The SQLAlchemy expression works with asyncpg. If you hit a dialect error, replace with a Python-level `seen` set after fetching.
