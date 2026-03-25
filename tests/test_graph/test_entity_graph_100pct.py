"""
test_entity_graph_100pct.py — Coverage for entity_graph.py missing branches.

Targets:
  - Lines 428-432: "address" entity type in get_nodes_paginated
  - Lines 435-443: "phone" entity type in get_nodes_paginated
  - Lines 446-454: "email" entity type in get_nodes_paginated
  - Lines 457-471: "company" entity type in get_nodes_paginated
  - Line 534: from_id == to_id early return in find_shortest_path
  - Line 580: non-person entity type in expand_entity
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph.entity_graph import EntityGraphBuilder


def _make_session(rows=None):
    """Build a mock session that returns rows for all execute calls."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows or []
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# get_nodes_paginated — entity-type branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_nodes_paginated_address_type():
    """Lines 428-432: 'address' entity type queries Address table."""
    builder = EntityGraphBuilder()
    addr = MagicMock()
    addr.id = uuid.uuid4()
    addr.street = "123 Main St"
    addr.city = "Austin"
    addr.state_province = "TX"

    session = _make_session(rows=[addr])
    nodes = await builder.get_nodes_paginated(session, entity_types=["address"])
    # Should have at least one address node
    assert any(n["type"] == "address" for n in nodes)


@pytest.mark.asyncio
async def test_get_nodes_paginated_phone_type():
    """Lines 435-443: 'phone' entity type queries Identifier table."""
    builder = EntityGraphBuilder()
    ident = MagicMock()
    ident.id = uuid.uuid4()
    ident.value = "+15551234567"

    session = _make_session(rows=[ident])
    nodes = await builder.get_nodes_paginated(session, entity_types=["phone"])
    assert any(n["type"] == "phone" for n in nodes)


@pytest.mark.asyncio
async def test_get_nodes_paginated_email_type():
    """Lines 446-454: 'email' entity type queries Identifier table."""
    builder = EntityGraphBuilder()
    ident = MagicMock()
    ident.id = uuid.uuid4()
    ident.value = "test@example.com"

    session = _make_session(rows=[ident])
    nodes = await builder.get_nodes_paginated(session, entity_types=["email"])
    assert any(n["type"] == "email" for n in nodes)


@pytest.mark.asyncio
async def test_get_nodes_paginated_company_type():
    """Lines 457-471: 'company' entity type queries EmploymentHistory."""
    builder = EntityGraphBuilder()
    emp = MagicMock()
    emp.employer_name = "Acme Corp"

    session = _make_session(rows=[emp])
    nodes = await builder.get_nodes_paginated(session, entity_types=["company"])
    assert any(n["type"] == "company" for n in nodes)


@pytest.mark.asyncio
async def test_get_nodes_paginated_duplicate_company_deduplicated():
    """Company nodes are deduplicated by name."""
    builder = EntityGraphBuilder()
    emp1 = MagicMock()
    emp1.employer_name = "Acme Corp"
    emp2 = MagicMock()
    emp2.employer_name = "Acme Corp"

    session = _make_session(rows=[emp1, emp2])
    nodes = await builder.get_nodes_paginated(session, entity_types=["company"])
    company_nodes = [n for n in nodes if n["type"] == "company"]
    assert len(company_nodes) == 1


@pytest.mark.asyncio
async def test_get_nodes_paginated_address_no_street():
    """Address node label falls back to str(id) when no fields set."""
    builder = EntityGraphBuilder()
    addr = MagicMock()
    addr.id = uuid.uuid4()
    addr.street = None
    addr.city = None
    addr.state_province = None

    session = _make_session(rows=[addr])
    nodes = await builder.get_nodes_paginated(session, entity_types=["address"])
    assert any(n["type"] == "address" for n in nodes)


# ---------------------------------------------------------------------------
# find_shortest_path — from_id == to_id early return (line 534)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_shortest_path_same_node():
    """Line 534: from_id == to_id → immediate return path=[from_id], edges=[]."""
    builder = EntityGraphBuilder()
    node_id = str(uuid.uuid4())

    session = _make_session(rows=[])
    result = await builder.find_shortest_path(node_id, node_id, session, entity_types=None)
    assert result["path"] == [node_id]
    assert result["edges"] == []


# ---------------------------------------------------------------------------
# expand_entity — non-person stub return (line 580)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expand_entity_non_person_returns_stub():
    """Line 580: entity_type != 'person' → return stub node with no edges."""
    builder = EntityGraphBuilder()
    session = _make_session(rows=[])

    result = await builder.expand_entity("address", "some-addr-id", session)
    assert result["edges"] == []
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["type"] == "address"


@pytest.mark.asyncio
async def test_expand_entity_company_returns_stub():
    """Confirm 'company' entity type also returns stub."""
    builder = EntityGraphBuilder()
    session = _make_session(rows=[])

    result = await builder.expand_entity("company", "some-company-id", session)
    assert result["edges"] == []
    assert result["nodes"][0]["type"] == "company"


@pytest.mark.asyncio
async def test_expand_entity_unknown_type_raises():
    """Unsupported entity type raises ValueError."""
    builder = EntityGraphBuilder()
    session = _make_session(rows=[])

    with pytest.raises(ValueError, match="Unsupported entity_type"):
        await builder.expand_entity("unknown_type", "some-id", session)
