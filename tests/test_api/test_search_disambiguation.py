"""
test_search_disambiguation.py — Coverage for disambiguation + candidates endpoints
added to api/routes/search.py.

Covers:
  - _get_candidates: persons with date_of_birth (isoformat branch), without dob
  - _process_single: FULL_NAME with >1 match → requires_disambiguation=True
  - GET /search/candidates: full_name path, non-full_name path (identifier lookup),
    ident without person_id (skip), ident with missing person (skip),
    explicit seed_type query param
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import db_session
from api.routes.search import router


# ── App factory ───────────────────────────────────────────────────────────────


def _make_app(session):
    app = FastAPI()
    app.include_router(router, prefix="/search")

    async def _dep():
        yield session

    app.dependency_overrides[db_session] = _dep
    return app


# ── Session helpers ───────────────────────────────────────────────────────────


def _empty_session():
    session = AsyncMock()
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    empty.scalars.return_value.all.return_value = []
    empty.scalar.return_value = 0
    session.execute = AsyncMock(return_value=empty)
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_person(name="Alice Smith", dob: date | None = None):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = name
    p.date_of_birth = dob
    p.nationality = "US"
    p.default_risk_score = 0.1
    p.meta = {}
    return p


# ── GET /search/candidates — full_name path ───────────────────────────────────


def test_candidates_full_name_returns_empty_when_no_match():
    session = _empty_session()
    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get("/search/candidates", params={"value": "John Smith"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["candidates"] == []
    assert data["seed_type"] == "full_name"


def test_candidates_full_name_returns_persons_with_dob():
    """Covers _get_candidates loop + date_of_birth.isoformat() branch (lines 271-275)."""
    session = _empty_session()
    person = _make_person("John Smith", dob=date(1985, 6, 15))

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [person]

    count_result = MagicMock()
    count_result.scalar.return_value = 3

    session.execute = AsyncMock(side_effect=[persons_result, count_result])

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get("/search/candidates", params={"value": "John Smith"})

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["candidates"][0]["full_name"] == "John Smith"
    assert data["candidates"][0]["date_of_birth"] == "1985-06-15"
    assert data["candidates"][0]["identifier_count"] == 3


def test_candidates_full_name_none_dob():
    """Covers date_of_birth None branch (returns null)."""
    session = _empty_session()
    person = _make_person("Jane Doe", dob=None)

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [person]

    count_result = MagicMock()
    count_result.scalar.return_value = 0

    session.execute = AsyncMock(side_effect=[persons_result, count_result])

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get("/search/candidates", params={"value": "Jane Doe"})

    assert r.status_code == 200
    data = r.json()
    assert data["candidates"][0]["date_of_birth"] is None


# ── GET /search/candidates — non-full_name path ───────────────────────────────


def test_candidates_email_returns_linked_person():
    """Covers non-FULL_NAME path: identifier lookup → person → count (lines 425-464)."""
    session = _empty_session()
    pid = uuid.uuid4()
    person = _make_person("Bob Brown")
    person.id = pid

    ident = MagicMock()
    ident.person_id = pid

    idents_result = MagicMock()
    idents_result.scalars.return_value.all.return_value = [ident]

    count_result = MagicMock()
    count_result.scalar.return_value = 5

    session.execute = AsyncMock(side_effect=[idents_result, count_result])
    session.get = AsyncMock(return_value=person)

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get(
            "/search/candidates",
            params={"value": "bob@example.com", "seed_type": "email"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["seed_type"] == "email"
    assert data["count"] == 1
    assert data["candidates"][0]["identifier_count"] == 5


def test_candidates_skips_ident_without_person_id():
    """Covers ident.person_id is None → continue (line 440-441)."""
    session = _empty_session()

    ident = MagicMock()
    ident.person_id = None  # no person linked

    idents_result = MagicMock()
    idents_result.scalars.return_value.all.return_value = [ident]

    session.execute = AsyncMock(return_value=idents_result)

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get(
            "/search/candidates",
            params={"value": "bob@example.com", "seed_type": "email"},
        )

    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_candidates_skips_ident_when_person_not_found():
    """Covers session.get returns None → continue (lines 442-444)."""
    session = _empty_session()
    pid = uuid.uuid4()

    ident = MagicMock()
    ident.person_id = pid

    idents_result = MagicMock()
    idents_result.scalars.return_value.all.return_value = [ident]

    session.execute = AsyncMock(return_value=idents_result)
    session.get = AsyncMock(return_value=None)  # person missing

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get(
            "/search/candidates",
            params={"value": "bob@example.com", "seed_type": "email"},
        )

    assert r.status_code == 200
    assert r.json()["count"] == 0


# ── POST /search disambiguation trigger ──────────────────────────────────────


def test_search_full_name_disambiguation_when_multiple_persons():
    """Covers lines 295-302: >1 candidate → requires_disambiguation=True."""
    session = _empty_session()

    p1 = _make_person("John Smith")
    p2 = _make_person("John Smith")

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [p1, p2]

    count_result1 = MagicMock(); count_result1.scalar.return_value = 2
    count_result2 = MagicMock(); count_result2.scalar.return_value = 1

    # First execute → persons list, then two count queries
    session.execute = AsyncMock(side_effect=[persons_result, count_result1, count_result2])

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.post("/search", json={"value": "John Smith"})

    assert r.status_code == 200
    data = r.json()
    assert data["requires_disambiguation"] is True
    assert len(data["candidates"]) == 2
    assert data["person_id"] == ""
