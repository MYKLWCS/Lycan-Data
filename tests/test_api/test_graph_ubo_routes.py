"""
test_graph_ubo_routes.py — Coverage for new UBO/company-intel routes in api/routes/graph.py.

Targets:
  - POST /company/intel  (lines 229-260)
  - POST /company/ubo    (lines 266-299)
  - GET  /company/{id}/persons  (lines 309-341)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import db_session
from api.routes.graph import router
from modules.graph.ubo_discovery import (
    CrawledCompanyData,
    PersonRef,
    UBOCandidate,
    UBOResult,
)


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _make_session():
    session = AsyncMock()
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    r.scalar_one_or_none.return_value = None
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


def _empty_crawled(name: str = "Acme Corp") -> CrawledCompanyData:
    return CrawledCompanyData(
        company_name=name, jurisdiction="us", company_numbers=["12345"],
        registered_addresses=["123 Main St"], status="active",
        incorporation_date="2010-01-01", entity_type="LLC", lei="LEI123",
        officers=[
            PersonRef(name="Alice Smith", source="opencorporates", position="director",
                      jurisdiction="us", company_name=name, confidence=0.85)
        ],
        sec_filings=[{"form_type": "10-K", "date": "2024-01-01"}],
        has_proxy_filing=False, data_sources=["opencorporates"],
        crawl_errors=["gleif:timeout"],
    )


def _empty_ubo_result(name: str = "Acme Corp") -> UBOResult:
    pid = str(uuid.uuid4())
    return UBOResult(
        root_company=name,
        jurisdiction="us",
        max_depth_used=3,
        nodes=[{"id": f"company:{uuid.uuid4()}", "type": "company", "label": name}],
        edges=[],
        ubo_candidates=[
            UBOCandidate(
                name="Alice Smith", person_id=pid, chain=[name, "Alice Smith"],
                depth=1, controlling_roles=["director"], jurisdictions=["us"],
                confidence=0.85, is_natural_person=True, sanctions_hits=[],
                risk_score=0.0,
            )
        ],
        risk_flags=[],
        crawl_errors=[],
        discovered_at=datetime.now(UTC),
        partial=False,
    )


# ── POST /company/intel ────────────────────────────────────────────────────────


def test_company_intel_returns_200():
    session = _make_session()
    app = _make_app(session)
    crawled = _empty_crawled()

    with patch("api.routes.graph._ubo_engine") as mock_engine:
        mock_engine.crawl_company = AsyncMock(return_value=crawled)
        with TestClient(app) as client:
            r = client.post("/graph/company/intel", json={"company_name": "Acme Corp"})

    assert r.status_code == 200
    data = r.json()
    assert data["company_name"] == "Acme Corp"
    assert data["lei"] == "LEI123"
    assert len(data["officers"]) == 1
    assert data["officers"][0]["name"] == "Alice Smith"
    assert data["has_proxy_filing"] is False


def test_company_intel_returns_500_on_exception():
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._ubo_engine") as mock_engine:
        mock_engine.crawl_company = AsyncMock(side_effect=RuntimeError("crawler down"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/graph/company/intel", json={"company_name": "Broken Corp"})

    assert r.status_code == 500


def test_company_intel_with_jurisdiction():
    session = _make_session()
    app = _make_app(session)
    crawled = _empty_crawled()
    crawled.jurisdiction = "gb"

    with patch("api.routes.graph._ubo_engine") as mock_engine:
        mock_engine.crawl_company = AsyncMock(return_value=crawled)
        with TestClient(app) as client:
            r = client.post("/graph/company/intel", json={"company_name": "UK Corp", "jurisdiction": "gb"})

    assert r.status_code == 200
    assert r.json()["jurisdiction"] == "gb"


# ── POST /company/ubo ─────────────────────────────────────────────────────────


def test_company_ubo_returns_200():
    session = _make_session()
    app = _make_app(session)
    ubo_result = _empty_ubo_result()

    with patch("api.routes.graph._ubo_engine") as mock_engine:
        mock_engine.discover = AsyncMock(return_value=ubo_result)
        with TestClient(app) as client:
            r = client.post("/graph/company/ubo", json={"company_name": "Acme Corp", "max_depth": 3})

    assert r.status_code == 200
    data = r.json()
    assert data["root_company"] == "Acme Corp"
    assert data["partial"] is False
    assert len(data["ubo_candidates"]) == 1
    assert data["ubo_candidates"][0]["name"] == "Alice Smith"
    assert "discovered_at" in data


def test_company_ubo_returns_500_on_exception():
    session = _make_session()
    app = _make_app(session)

    with patch("api.routes.graph._ubo_engine") as mock_engine:
        mock_engine.discover = AsyncMock(side_effect=RuntimeError("BFS exploded"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/graph/company/ubo", json={"company_name": "Broken Corp"})

    assert r.status_code == 500


def test_company_ubo_with_risk_flags():
    session = _make_session()
    app = _make_app(session)
    ubo_result = _empty_ubo_result()
    ubo_result.risk_flags = ["offshore_jurisdiction", "shell_company_chain"]
    ubo_result.partial = True

    with patch("api.routes.graph._ubo_engine") as mock_engine:
        mock_engine.discover = AsyncMock(return_value=ubo_result)
        with TestClient(app) as client:
            r = client.post("/graph/company/ubo", json={"company_name": "Offshore LLC"})

    data = r.json()
    assert "offshore_jurisdiction" in data["risk_flags"]
    assert data["partial"] is True


# ── GET /company/{company_id}/persons ─────────────────────────────────────────


def test_company_persons_returns_empty_list():
    session = _make_session()
    app = _make_app(session)

    with TestClient(app) as client:
        r = client.get("/graph/company/acme-corp/persons")

    assert r.status_code == 200
    data = r.json()
    assert data["company_id"] == "acme-corp"
    assert data["persons"] == []
    assert data["count"] == 0


def test_company_persons_with_uuid_company_id():
    session = _make_session()
    app = _make_app(session)
    company_id = str(uuid.uuid4())

    with TestClient(app) as client:
        r = client.get(f"/graph/company/{company_id}/persons")

    assert r.status_code == 200
    assert r.json()["company_id"] == company_id


def test_company_persons_returns_500_on_exception():
    session = _make_session()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    app = _make_app(session)

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/graph/company/acme-corp/persons")

    assert r.status_code == 500


def test_company_persons_returns_persons_when_found():
    session = _make_session()
    pid = uuid.uuid4()
    mock_person = MagicMock()
    mock_person.id = pid
    mock_person.full_name = "Alice Smith"
    mock_person.default_risk_score = 0.0
    mock_person.date_of_birth = None
    mock_person.gender = None
    mock_person.meta = {}

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [mock_person]
    session.execute = AsyncMock(return_value=result_mock)

    app = _make_app(session)
    with TestClient(app) as client:
        r = client.get("/graph/company/acme-corp/persons")

    assert r.status_code == 200
    assert r.json()["count"] == 1
