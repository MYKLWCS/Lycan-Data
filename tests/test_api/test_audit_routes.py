"""Tests for /audit/* API endpoints — Task 4 of Phase 6.

All DB sessions are mocked via FastAPI dependency overrides.
Tests verify routing, response shape, and status codes.
"""

import uuid
from datetime import timezone, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

import shared.models  # noqa: F401 — force full mapper resolution
from api.deps import db_session
from api.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _make_audit_row(**kwargs):
    """Build a minimal SystemAudit-like dict for endpoint response checks."""
    defaults = {
        "id": uuid.uuid4(),
        "run_at": datetime.now(timezone.utc),
        "persons_total": 100,
        "persons_low_coverage": 10,
        "persons_stale": 5,
        "persons_conflict": 2,
        "crawlers_total": 8,
        "crawlers_healthy": 7,
        "crawlers_degraded": [{"name": "twitter", "success_rate": 0.0}],
        "tags_assigned_today": 50,
        "merges_today": 3,
        "persons_ingested_today": 20,
        "meta": {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# Client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_session():
    return _make_session()


# ---------------------------------------------------------------------------
# GET /audit/latest
# ---------------------------------------------------------------------------


def test_audit_latest_returns_snapshot(client, mock_session):
    row = _make_audit_row()

    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    mock_session.execute = AsyncMock(return_value=result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert "persons_total" in data
        assert data["persons_total"] == 100
    finally:
        app.dependency_overrides.pop(db_session, None)


def test_audit_latest_returns_404_when_no_data(client, mock_session):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/latest")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(db_session, None)


# ---------------------------------------------------------------------------
# POST /audit/run
# ---------------------------------------------------------------------------


def test_audit_run_triggers_background_task(client):
    with patch("modules.audit.audit_daemon.AuditDaemon") as MockDaemon:
        mock_instance = MagicMock()
        mock_instance._run_audit = AsyncMock()
        MockDaemon.return_value = mock_instance

        resp = client.post("/audit/run")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "triggered"


# ---------------------------------------------------------------------------
# GET /audit/history
# ---------------------------------------------------------------------------


def test_audit_history_returns_list(client, mock_session):
    rows = [_make_audit_row(), _make_audit_row()]

    scalars_result = MagicMock()
    scalars_result.all.return_value = rows
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars_result
    mock_session.execute = AsyncMock(return_value=exec_result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/history?limit=30")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
    finally:
        app.dependency_overrides.pop(db_session, None)


def test_audit_history_default_limit(client, mock_session):
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars_result
    mock_session.execute = AsyncMock(return_value=exec_result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
    finally:
        app.dependency_overrides.pop(db_session, None)


# ---------------------------------------------------------------------------
# GET /audit/crawlers
# ---------------------------------------------------------------------------


def test_audit_crawlers_returns_health(client, mock_session):
    crawl_rows = [
        {"job_type": "twitter", "found_count": 0, "error_count": 5, "total_jobs": 5},
        {"job_type": "linkedin", "found_count": 10, "error_count": 2, "total_jobs": 12},
    ]
    mappings_result = MagicMock()
    mappings_result.all.return_value = crawl_rows
    exec_result = MagicMock()
    exec_result.mappings.return_value = mappings_result
    mock_session.execute = AsyncMock(return_value=exec_result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/crawlers")
        assert resp.status_code == 200
        data = resp.json()
        assert "crawlers" in data
        assert isinstance(data["crawlers"], list)
    finally:
        app.dependency_overrides.pop(db_session, None)


# ---------------------------------------------------------------------------
# GET /audit/persons/stale
# ---------------------------------------------------------------------------


def test_audit_persons_stale_returns_list(client, mock_session):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = "John Doe"
    p.last_scraped_at = datetime.now(timezone.utc)
    p.meta = {}

    scalars_result = MagicMock()
    scalars_result.all.return_value = [p]
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars_result
    mock_session.execute = AsyncMock(return_value=exec_result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/persons/stale?limit=50&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["full_name"] == "John Doe"
    finally:
        app.dependency_overrides.pop(db_session, None)


# ---------------------------------------------------------------------------
# GET /audit/persons/low-coverage
# ---------------------------------------------------------------------------


def test_audit_persons_low_coverage_returns_list(client, mock_session):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = "Jane Smith"
    p.meta = {"coverage": {"pct": 25}}
    p.last_scraped_at = None

    scalars_result = MagicMock()
    scalars_result.all.return_value = [p]
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars_result
    mock_session.execute = AsyncMock(return_value=exec_result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override
    try:
        resp = client.get("/audit/persons/low-coverage?limit=50&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["full_name"] == "Jane Smith"
    finally:
        app.dependency_overrides.pop(db_session, None)
