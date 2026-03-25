"""
test_persons_wave5.py — Coverage gap tests for api/routes/persons.py.

Targets:
  - Line 368 (formerly reported as 356): q = q.order_by(order_by) inside _fetch()
    when order_by is not None. This branch is hit by any _fetch call that passes
    an order_by argument inside get_report.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import db_session
from api.routes.persons import router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_col(name: str, val) -> MagicMock:
    col = MagicMock()
    col.name = name
    return col


def _make_mock_person(person_id: uuid.UUID) -> MagicMock:
    """Build a Person-like mock that has __table__.columns so _model_to_dict works."""
    p = MagicMock()
    p.id = person_id
    p.full_name = "Test Person"
    p.date_of_birth = None
    p.dob = None
    p.gender = None
    p.nationality = "US"
    p.primary_language = None
    p.bio = None
    p.profile_image_url = None
    p.meta = {}
    p.merged_into = None
    p.relationship_score = 0.0
    p.behavioural_risk = 0.0
    p.darkweb_exposure = 0.0
    p.default_risk_score = 0.0
    p.risk_score = 0.0
    p.freshness_score = 0.5
    p.source_reliability = 0.9
    p.conflict_flag = False
    p.created_at = None
    p.updated_at = None
    p.data_quality_score = None
    p.corroboration_count = 0

    # __table__.columns is needed by _model_to_dict
    col_names = [
        "id",
        "full_name",
        "date_of_birth",
        "gender",
        "nationality",
        "primary_language",
        "bio",
        "profile_image_url",
        "meta",
        "relationship_score",
        "behavioural_risk",
        "darkweb_exposure",
        "default_risk_score",
    ]
    cols = []
    for name in col_names:
        col = MagicMock()
        col.name = name
        cols.append(col)
    p.__table__ = MagicMock()
    p.__table__.columns = cols

    return p


def _make_session(person):
    session = AsyncMock()
    session.get = AsyncMock(return_value=person)

    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[])
    exec_result = MagicMock()
    exec_result.scalars = MagicMock(return_value=scalars_result)
    exec_result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=exec_result)
    return session


def _override_db(session):
    async def _dep():
        yield session

    return _dep


def _make_app(session):
    app = FastAPI()
    app.include_router(router, prefix="/persons")
    app.dependency_overrides[db_session] = _override_db(session)
    return app


# ---------------------------------------------------------------------------
# Line 368: order_by branch inside _fetch
# ---------------------------------------------------------------------------


def test_get_report_triggers_order_by_branch():
    """
    Line 368: q = q.order_by(order_by) is reached when _fetch is called with a
    non-None order_by argument inside get_report (e.g., for EmploymentHistory).
    Calling GET /persons/{id}/report with a valid person triggers _fetch calls
    that pass order_by, reaching the branch on this line.
    """
    pid = uuid.uuid4()
    person = _make_mock_person(pid)

    session = _make_session(person)
    app = _make_app(session)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/persons/{pid}/report")

    # 200 = route completed and _fetch(order_by=...) was called
    assert response.status_code == 200
    # session.execute was called multiple times via _fetch
    assert session.execute.await_count >= 1


def test_get_report_execute_called_multiple_times():
    """
    Line 368: Multiple _fetch invocations within get_report verify the execute
    path runs repeatedly — including those with order_by arguments.
    """
    pid = uuid.uuid4()
    person = _make_mock_person(pid)

    session = _make_session(person)
    app = _make_app(session)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/persons/{pid}/report")

    assert response.status_code == 200
    # get_report calls _fetch at least 10+ times
    assert session.execute.await_count >= 5
