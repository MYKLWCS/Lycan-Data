"""
test_entity_graph_wave6.py — Coverage for modules/graph/entity_graph.py missing lines.

Targets:
  - Line 77   : frontier empty early break (depth loop exits early when no frontier)
  - Line 145  : social profile label: sp.handle is falsy → use platform_user_id
  - Line 189  : identifier type not in allowed list → skip (continue branch)
  - Lines 208-211: social profile nodes and edges appended
  - Line 217  : relationship deduplication (rel.id already in seen_rels → skip)
  - Lines 307-309: find_shared_connections — emp_map loop (employer name + person_id)
  - Lines 312-313: find_shared_connections — shared employer appended
  - Lines 375-376: detect_fraud_rings — phone_cluster loop
  - Lines 379-383: detect_fraud_rings — phone ring appended
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph.entity_graph import EntityGraphBuilder

# ── Helpers ───────────────────────────────────────────────────────────────────


def _scalars_result(items: list) -> MagicMock:
    sm = MagicMock()
    sm.all.return_value = items
    rm = MagicMock()
    rm.scalars.return_value = sm
    return rm


def _empty() -> MagicMock:
    return _scalars_result([])


def _make_session(side_effects: list) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=side_effects)
    return session


def _make_person(name="Alice", risk=0.3):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = name
    p.default_risk_score = risk
    return p


# ── Line 77: frontier empty early break ───────────────────────────────────────


@pytest.mark.asyncio
async def test_build_person_graph_depth2_empty_frontier_early_break():
    """
    Line 77: When no relationships exist at depth=1, next_frontier is empty.
    The loop breaks early at depth=2 because frontier is empty.
    """
    person_id = uuid.uuid4()
    person = _make_person("Bob")
    person.id = person_id

    builder = EntityGraphBuilder()

    # depth=2 means 2 iterations. First iteration: no relationships → frontier empty.
    # Second iteration starts but frontier=empty → hits line 77 (break).
    session = _make_session(
        [
            _scalars_result([person]),  # persons at hop 1
            _empty(),  # addresses
            _empty(),  # identifiers
            _empty(),  # employment
            _empty(),  # social profiles
            _empty(),  # relationships — no neighbours, frontier will be empty
            # hop 2 never fires because frontier is empty — line 77 breaks the loop
        ]
    )

    graph = await builder.build_person_graph(str(person_id), session, depth=2)
    assert any(n["id"] == str(person_id) for n in graph["nodes"])


# ── Line 145: social profile label — handle is falsy, use platform_user_id ───


@pytest.mark.asyncio
async def test_build_person_graph_social_profile_no_handle_uses_platform_user_id():
    """
    Line 145: social profile label falls back to platform_user_id when handle is None.
    """
    person_id = uuid.uuid4()
    person = _make_person("Carol")
    person.id = person_id

    sp = MagicMock()
    sp.id = uuid.uuid4()
    sp.person_id = person_id
    sp.platform = "twitter"
    sp.handle = None  # falsy — triggers the or branch
    sp.platform_user_id = "uid_12345"

    builder = EntityGraphBuilder()
    session = _make_session(
        [
            _scalars_result([person]),
            _empty(),  # addresses
            _empty(),  # identifiers
            _empty(),  # employment
            _scalars_result([sp]),  # social profiles
            _empty(),  # relationships
        ]
    )

    graph = await builder.build_person_graph(str(person_id), session, depth=1)
    social_nodes = [n for n in graph["nodes"] if n["type"] == "social_profile"]
    assert len(social_nodes) == 1
    assert "uid_12345" in social_nodes[0]["label"]


# ── Line 189: identifier type not in allowed set → skip ───────────────────────


@pytest.mark.asyncio
async def test_build_person_graph_skips_unknown_identifier_types():
    """
    Line 189: Identifier with type 'national_id' (not in allowed set) is skipped.
    Only 'phone', 'email', 'ssn', 'passport' are processed.
    """
    person_id = uuid.uuid4()
    person = _make_person("Dave")
    person.id = person_id

    # This identifier has an unrecognised type — must hit the `continue` on line 189
    ident_bad = MagicMock()
    ident_bad.id = uuid.uuid4()
    ident_bad.person_id = person_id
    ident_bad.type = "national_id"  # not in allowed types
    ident_bad.value = "ZA-123456789"
    ident_bad.confidence = 0.9

    # A valid phone identifier — should be processed
    ident_phone = MagicMock()
    ident_phone.id = uuid.uuid4()
    ident_phone.person_id = person_id
    ident_phone.type = "phone"
    ident_phone.value = "+27821234567"
    ident_phone.confidence = 1.0

    builder = EntityGraphBuilder()
    session = _make_session(
        [
            _scalars_result([person]),
            _empty(),  # addresses
            _scalars_result([ident_bad, ident_phone]),  # identifiers
            _empty(),  # employment
            _empty(),  # social profiles
            _empty(),  # relationships
        ]
    )

    graph = await builder.build_person_graph(str(person_id), session, depth=1)

    ident_nodes = [n for n in graph["nodes"] if n["type"] in ("phone", "email", "identifier")]
    # Only the phone ident should appear
    assert len(ident_nodes) == 1
    assert ident_nodes[0]["type"] == "phone"
    assert ident_nodes[0]["label"] == "+27821234567"


# ── Lines 208-211: social profile nodes appended ─────────────────────────────


@pytest.mark.asyncio
async def test_build_person_graph_social_profile_with_handle():
    """
    Lines 208-211: Social profile node is created when handle is provided.
    """
    person_id = uuid.uuid4()
    person = _make_person("Eve")
    person.id = person_id

    sp = MagicMock()
    sp.id = uuid.uuid4()
    sp.person_id = person_id
    sp.platform = "linkedin"
    sp.handle = "eve-smith"
    sp.platform_user_id = "li_999"

    builder = EntityGraphBuilder()
    session = _make_session(
        [
            _scalars_result([person]),
            _empty(),
            _empty(),
            _empty(),
            _scalars_result([sp]),
            _empty(),
        ]
    )

    graph = await builder.build_person_graph(str(person_id), session, depth=1)

    social_nodes = [n for n in graph["nodes"] if n["type"] == "social_profile"]
    assert len(social_nodes) == 1
    assert "linkedin" in social_nodes[0]["label"]
    assert "eve-smith" in social_nodes[0]["label"]

    edge_types = {e["type"] for e in graph["edges"]}
    assert "has_social" in edge_types


# ── Line 217: relationship deduplication ─────────────────────────────────────


@pytest.mark.asyncio
async def test_build_person_graph_deduplicates_duplicate_relationships():
    """
    Line 217: If the same relationship appears twice (person_a and person_b both
    reference it), the second occurrence is skipped via seen_rels.
    """
    person_id = uuid.uuid4()
    person = _make_person("Frank")
    person.id = person_id

    other_id = uuid.uuid4()

    rel = MagicMock()
    rel.id = uuid.uuid4()
    rel.person_a_id = person_id
    rel.person_b_id = other_id
    rel.rel_type = "associate"
    rel.score = 0.8

    # Provide the SAME relationship object TWICE in rel_by_pid
    # This happens naturally when person_a_id == pid and person_b_id == pid for the same rel
    # We simulate it by putting the relationship twice in the list
    builder = EntityGraphBuilder()
    session = _make_session(
        [
            _scalars_result([person]),
            _empty(),
            _empty(),
            _empty(),
            _empty(),
            _scalars_result([rel, rel]),  # duplicate relationship row
        ]
    )

    graph = await builder.build_person_graph(str(person_id), session, depth=1)

    # Despite duplicate rows, the edge should appear only once
    edges_to_other = [
        e for e in graph["edges"] if e["source"] == str(person_id) and e["target"] == str(other_id)
    ]
    assert len(edges_to_other) == 1


# ── Lines 307-313: find_shared_connections — shared employers ─────────────────


@pytest.mark.asyncio
async def test_find_shared_connections_detects_shared_employer():
    """
    Lines 307-313: Two persons at the same employer → shared employer result.
    """
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())
    pid_a_uuid = uuid.UUID(pid_a)
    pid_b_uuid = uuid.UUID(pid_b)

    def _emp(pid, company="Wolf Corp"):
        e = MagicMock()
        e.person_id = pid
        e.employer_name = company
        return e

    emp_a = _emp(pid_a_uuid)
    emp_b = _emp(pid_b_uuid)

    session = _make_session(
        [
            _empty(),  # identifiers
            _empty(),  # addresses
            _scalars_result([emp_a, emp_b]),  # employment
        ]
    )

    builder = EntityGraphBuilder()
    shared = await builder.find_shared_connections([pid_a, pid_b], session)

    employer_hits = [s for s in shared if s["type"] == "employer"]
    assert len(employer_hits) == 1
    assert employer_hits[0]["risk_implication"] == "shared_employer"
    assert "wolf corp" in employer_hits[0]["value"]


@pytest.mark.asyncio
async def test_find_shared_connections_skips_single_employer_match():
    """
    Lines 312-313: Only one person at an employer → NOT added to shared list.
    """
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())
    pid_a_uuid = uuid.UUID(pid_a)
    pid_b_uuid = uuid.UUID(pid_b)

    emp_a = MagicMock()
    emp_a.person_id = pid_a_uuid
    emp_a.employer_name = "Unique Corp"

    emp_b = MagicMock()
    emp_b.person_id = pid_b_uuid
    emp_b.employer_name = "Other Corp"

    session = _make_session(
        [
            _empty(),
            _empty(),
            _scalars_result([emp_a, emp_b]),
        ]
    )

    builder = EntityGraphBuilder()
    shared = await builder.find_shared_connections([pid_a, pid_b], session)

    employer_hits = [s for s in shared if s["type"] == "employer"]
    assert len(employer_hits) == 0


# ── Lines 375-383: detect_fraud_rings — phone cluster ────────────────────────


@pytest.mark.asyncio
async def test_detect_fraud_rings_detects_phone_cluster():
    """
    Lines 375-383: Multiple persons sharing the same phone → phone ring appended.
    """
    pids = [uuid.uuid4() for _ in range(3)]
    shared_phone = "+15559998888"

    def _phone_row(pid, phone=shared_phone):
        r = MagicMock()
        r.person_id = pid
        r.normalized_value = phone
        r.value = phone
        return r

    phone_rows = [_phone_row(p) for p in pids]

    session = _make_session(
        [
            _empty(),  # addresses
            _scalars_result(phone_rows),  # phones
        ]
    )

    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)

    phone_rings = [r for r in rings if "phone" in r["shared_element"]]
    assert len(phone_rings) == 1
    ring = phone_rings[0]
    assert len(ring["persons"]) == 3
    assert ring["risk_score"] >= 0.5
    assert shared_phone in ring["shared_element"]


@pytest.mark.asyncio
async def test_detect_fraud_rings_phone_risk_score_scales_with_size():
    """
    Lines 381-382: Risk score increases with more persons above min_connections.
    """
    pids = [uuid.uuid4() for _ in range(5)]
    shared_phone = "+15551112222"

    phone_rows = [
        MagicMock(person_id=p, normalized_value=shared_phone, value=shared_phone) for p in pids
    ]

    session = _make_session(
        [
            _empty(),
            _scalars_result(phone_rows),
        ]
    )

    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)

    phone_rings = [r for r in rings if "phone" in r["shared_element"]]
    assert len(phone_rings) == 1
    # 5 persons, min=3 → risk = min(0.5 + 0.1*(5-3), 1.0) = 0.7
    assert phone_rings[0]["risk_score"] == pytest.approx(0.7, abs=0.01)


@pytest.mark.asyncio
async def test_detect_fraud_rings_phone_cluster_below_min_connections_not_included():
    """
    Lines 379-380: Phone cluster below min_connections threshold is NOT included.
    """
    pids = [uuid.uuid4() for _ in range(2)]  # only 2 persons
    shared_phone = "+15550000001"

    phone_rows = [
        MagicMock(person_id=p, normalized_value=shared_phone, value=shared_phone) for p in pids
    ]

    session = _make_session(
        [
            _empty(),
            _scalars_result(phone_rows),
        ]
    )

    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)

    # Only 2 persons for the phone → below min_connections=3
    assert len(rings) == 0


@pytest.mark.asyncio
async def test_detect_fraud_rings_phone_only_normalized_value_is_none_falls_back_to_value():
    """
    Line 375: When normalized_value is None, falls back to row.value for the key.
    """
    pids = [uuid.uuid4() for _ in range(3)]
    raw_phone = "+15554443333"

    phone_rows = [MagicMock(person_id=p, normalized_value=None, value=raw_phone) for p in pids]

    session = _make_session(
        [
            _empty(),
            _scalars_result(phone_rows),
        ]
    )

    builder = EntityGraphBuilder()
    rings = await builder.detect_fraud_rings(session, min_connections=3)

    phone_rings = [r for r in rings if "phone" in r["shared_element"]]
    assert len(phone_rings) == 1
