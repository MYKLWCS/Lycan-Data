"""Tests for modules/graph/company_intel.py — CompanyIntelligenceEngine + helpers.

All DB interaction is mocked via AsyncMock; no live PostgreSQL required.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph.company_intel import (
    CompanyIntelligenceEngine,
    CompanyRecord,
    _build_record_from_rows,
)

# ---------------------------------------------------------------------------
# _build_record_from_rows (pure helper — no DB)
# ---------------------------------------------------------------------------


def _make_emp(
    employer: str,
    person_id: uuid.UUID | None = None,
    job_title: str | None = None,
    is_current: bool = False,
    location: str | None = None,
    meta: dict | None = None,
) -> MagicMock:
    row = MagicMock()
    row.person_id = person_id
    row.employer_name = employer
    row.job_title = job_title
    row.is_current = is_current
    row.location = location
    row.meta = meta or {}
    return row


def _make_person(person_id: uuid.UUID, name: str, risk: float = 0.0) -> MagicMock:
    p = MagicMock()
    p.id = person_id
    p.full_name = name
    p.default_risk_score = risk
    return p


def test_build_record_returns_company_record():
    emp = _make_emp("Acme Corp")
    record = _build_record_from_rows("Acme Corp", [emp], [])
    assert isinstance(record, CompanyRecord)
    assert record.legal_name == "Acme Corp"


def test_build_record_active_when_any_current():
    emp1 = _make_emp("Acme", is_current=False)
    emp2 = _make_emp("Acme", is_current=True)
    record = _build_record_from_rows("Acme", [emp1, emp2], [])
    assert record.status == "active"


def test_build_record_unknown_when_no_current():
    emp = _make_emp("OldCo", is_current=False)
    record = _build_record_from_rows("OldCo", [emp], [])
    assert record.status == "unknown"


def test_build_record_officer_resolved_via_person_rows():
    pid = uuid.uuid4()
    emp = _make_emp("TechCo", person_id=pid, job_title="CTO")
    person = _make_person(pid, "Eve")
    record = _build_record_from_rows("TechCo", [emp], [person])
    assert len(record.officers) == 1
    assert record.officers[0]["name"] == "Eve"
    assert record.officers[0]["title"] == "CTO"


def test_build_record_officer_fallback_to_employee():
    pid = uuid.uuid4()
    emp = _make_emp("BizCo", person_id=pid, job_title=None)
    record = _build_record_from_rows("BizCo", [emp], [])
    assert record.officers[0]["title"] == "Employee"


def test_build_record_hq_address_parsed_from_location():
    emp = _make_emp("HQ Corp", location="San Francisco, CA")
    record = _build_record_from_rows("HQ Corp", [emp], [])
    assert record.hq_address is not None
    assert record.hq_address["city"] == "San Francisco"
    assert record.hq_address["state"] == "CA"


def test_build_record_hq_address_single_part_location():
    """[91->93] location has only one part (no comma) → city set, state None."""
    emp = _make_emp("TexasCo", location="Austin")
    record = _build_record_from_rows("TexasCo", [emp], [])
    assert record.hq_address is not None
    assert record.hq_address["city"] == "Austin"
    assert record.hq_address["state"] is None


def test_build_record_website_from_meta():
    emp = _make_emp("WebCo", meta={"website": "https://webco.com"})
    record = _build_record_from_rows("WebCo", [emp], [])
    assert record.website == "https://webco.com"


def test_build_record_confidence_increases_with_rows():
    emps_1 = [_make_emp("Co") for _ in range(1)]
    emps_5 = [_make_emp("Co") for _ in range(5)]
    r1 = _build_record_from_rows("Co", emps_1, [])
    r5 = _build_record_from_rows("Co", emps_5, [])
    assert r5.confidence_score > r1.confidence_score


def test_build_record_confidence_capped_at_one():
    emps = [_make_emp("Big Co") for _ in range(100)]
    record = _build_record_from_rows("Big Co", emps, [])
    assert record.confidence_score <= 1.0


def test_build_record_deduplicates_officers():
    pid = uuid.uuid4()
    emp1 = _make_emp("DupCo", person_id=pid, job_title="CEO")
    emp2 = _make_emp("DupCo", person_id=pid, job_title="Chair")  # same person
    record = _build_record_from_rows("DupCo", [emp1, emp2], [])
    # Only one officer entry for the same person
    assert len(record.officers) == 1


# ---------------------------------------------------------------------------
# Session mock helpers
# ---------------------------------------------------------------------------


def _scalars_result(items: list) -> MagicMock:
    sm = MagicMock()
    sm.all.return_value = items
    rm = MagicMock()
    rm.scalars.return_value = sm
    return rm


def _scalar_one_or_none_result(item) -> MagicMock:
    rm = MagicMock()
    rm.scalar_one_or_none.return_value = item
    return rm


def _make_session(*results) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=list(results))
    return session


# ---------------------------------------------------------------------------
# search_company
# ---------------------------------------------------------------------------


async def test_search_company_returns_empty_when_no_rows():
    session = _make_session(_scalars_result([]))
    engine = CompanyIntelligenceEngine()
    result = await engine.search_company("Ghost Inc", None, session)
    assert result == []


async def test_search_company_returns_records():
    pid = uuid.uuid4()
    emp = _make_emp("Acme Corp", person_id=pid, job_title="CEO", is_current=True)
    person = _make_person(pid, "Frank")

    session = _make_session(
        _scalars_result([emp]),  # employment search
        _scalars_result([person]),  # person lookup
    )
    engine = CompanyIntelligenceEngine()
    records = await engine.search_company("acme", None, session)
    assert len(records) >= 1
    assert records[0].legal_name == "Acme Corp"


async def test_search_company_state_filter_removes_non_matching():
    pid = uuid.uuid4()
    emp_tx = _make_emp("BigCo TX", person_id=pid, location="Dallas, TX")
    emp_ca = _make_emp("BigCo CA", person_id=pid, location="Los Angeles, CA")

    session = _make_session(
        _scalars_result([emp_tx, emp_ca]),  # employment
        _scalars_result([]),  # persons (filtered down to TX)
    )
    engine = CompanyIntelligenceEngine()
    # State filter is applied after DB fetch; CA row should be excluded
    records = await engine.search_company("bigco", "TX", session)
    for r in records:
        assert "ca" not in r.legal_name.lower()


# ---------------------------------------------------------------------------
# get_company_network
# ---------------------------------------------------------------------------


async def test_get_company_network_returns_nodes_and_edges():
    pid = uuid.uuid4()
    emp = _make_emp("NetCo", person_id=pid, job_title="Director", is_current=True)
    person = _make_person(pid, "Grace")

    session = _make_session(
        _scalars_result([emp]),  # employment
        _scalars_result([person]),  # persons
        # No relationship query because only 1 person
    )
    engine = CompanyIntelligenceEngine()
    network = await engine.get_company_network("NetCo", session)
    assert "nodes" in network
    assert "edges" in network
    # Company node + person node
    assert len(network["nodes"]) >= 2
    assert any(n["type"] == "company" for n in network["nodes"])
    assert any(n["type"] == "person" for n in network["nodes"])


async def test_get_company_network_empty_when_no_employment():
    session = _make_session(_scalars_result([]))  # no employment rows
    engine = CompanyIntelligenceEngine()
    network = await engine.get_company_network("Ghost Corp", session)
    # Still returns structure with the company node, zero person nodes
    assert "nodes" in network
    company_nodes = [n for n in network["nodes"] if n["type"] == "company"]
    assert len(company_nodes) == 1


# ---------------------------------------------------------------------------
# get_person_companies
# ---------------------------------------------------------------------------


async def test_get_person_companies_returns_empty_when_no_rows():
    person_id = str(uuid.uuid4())
    session = _make_session(_scalars_result([]))
    engine = CompanyIntelligenceEngine()
    result = await engine.get_person_companies(person_id, session)
    assert result == []


async def test_get_person_companies_returns_one_record_per_employment():
    pid_uuid = uuid.uuid4()
    person_id = str(pid_uuid)

    emp1 = _make_emp("Company A", person_id=pid_uuid, is_current=True)
    emp2 = _make_emp("Company B", person_id=pid_uuid, is_current=False)
    person = _make_person(pid_uuid, "Heidi")

    session = _make_session(
        _scalars_result([emp1, emp2]),  # employment rows
        _scalar_one_or_none_result(person),  # person lookup
    )
    engine = CompanyIntelligenceEngine()
    records = await engine.get_person_companies(person_id, session)
    assert len(records) == 2
    names = {r.legal_name for r in records}
    assert names == {"Company A", "Company B"}
