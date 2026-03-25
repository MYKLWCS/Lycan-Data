"""
Company Intelligence Engine — builds CompanyRecord objects from existing DB tables.

No external APIs. All data sourced from:
  - shared.models.employment.EmploymentHistory
  - shared.models.relationship.Relationship
  - shared.models.social_profile.SocialProfile
  - shared.models.person.Person
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.employment import EmploymentHistory
from shared.models.person import Person
from shared.models.relationship import Relationship

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CompanyRecord:
    id: str
    legal_name: str
    dba_names: list[str]
    entity_type: str  # "llc" | "corporation" | "nonprofit" | "sole_prop" | "unknown"
    status: str  # "active" | "dissolved" | "suspended" | "unknown"
    state_of_incorporation: str | None
    incorporation_date: datetime | None
    ein: str | None
    website: str | None
    hq_address: dict | None  # {street, city, state, zip}
    officers: list[dict]  # [{name, title}]
    court_cases: list[dict]  # [{case_number, type, status}]
    data_sources: list[str]
    confidence_score: float
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_record_from_rows(
    employer_name: str,
    employment_rows: list[EmploymentHistory],
    person_rows: list[Person],
) -> CompanyRecord:
    """Assemble a CompanyRecord from a set of EmploymentHistory rows."""
    officers: list[dict] = []
    seen_persons: set[str] = set()

    for row in employment_rows:
        pid = str(row.person_id) if row.person_id else None
        if not pid or pid in seen_persons:
            continue
        seen_persons.add(pid)
        person = next((p for p in person_rows if str(p.id) == pid), None)
        name = person.full_name if person else pid
        title = row.job_title or "Employee"
        officers.append({"name": name, "title": title})

    # Derive status: if any current record exists → active
    has_current = any(r.is_current for r in employment_rows)
    status = "active" if has_current else "unknown"

    # Pull website from meta if present
    website: str | None = None
    for row in employment_rows:
        meta = row.meta or {}
        website = meta.get("website") or meta.get("url")
        if website:
            break

    # Derive hq_address from location field
    hq_address: dict | None = None
    for row in employment_rows:
        if row.location:
            parts = [p.strip() for p in row.location.split(",")]
            if len(parts) >= 2:
                hq_address = {"street": None, "city": parts[0], "state": parts[1], "zip": None}
            elif len(parts) == 1:  # pragma: no branch
                hq_address = {"street": None, "city": parts[0], "state": None, "zip": None}
            break

    confidence = min(0.3 + 0.07 * len(employment_rows), 1.0)

    return CompanyRecord(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, employer_name.lower().strip())),
        legal_name=employer_name,
        dba_names=[],
        entity_type="unknown",
        status=status,
        state_of_incorporation=None,
        incorporation_date=None,
        ein=None,
        website=website,
        hq_address=hq_address,
        officers=officers,
        court_cases=[],
        data_sources=["employment_history"],
        confidence_score=round(confidence, 3),
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CompanyIntelligenceEngine:
    """Query company data from the Lycan-Data relational store."""

    async def search_company(
        self,
        name: str,
        state: str | None,
        session: AsyncSession,
    ) -> list[CompanyRecord]:
        """
        Return up to 10 CompanyRecord objects matching `name`.

        Strategy:
          1. Pull EmploymentHistory rows where employer_name is a close match.
          2. Optionally filter by location when state is provided.
          3. Group by normalised employer_name and build one record per group.
        """
        name_lower = name.lower().strip()

        stmt = select(EmploymentHistory).where(
            func.lower(EmploymentHistory.employer_name).contains(name_lower)
        )
        result = await session.execute(stmt)
        rows: list[EmploymentHistory] = list(result.scalars().all())

        if not rows:
            return []

        # Filter by state if provided
        if state:
            state_lower = state.lower()
            rows = [r for r in rows if r.location and state_lower in r.location.lower()]

        if not rows:
            return []

        # Group by employer_name (case-insensitive)
        groups: dict[str, list[EmploymentHistory]] = {}
        for row in rows:
            key = (row.employer_name or "").lower().strip()
            groups.setdefault(key, []).append(row)

        # Collect person IDs for name resolution
        person_ids = list({str(r.person_id) for r in rows if r.person_id})
        person_rows: list[Person] = []
        if person_ids:
            p_stmt = select(Person).where(Person.id.in_([uuid.UUID(pid) for pid in person_ids]))
            p_result = await session.execute(p_stmt)
            person_rows = list(p_result.scalars().all())

        records = [
            _build_record_from_rows(
                emp_rows[0].employer_name or employer_name, emp_rows, person_rows
            )
            for employer_name, emp_rows in groups.items()
        ]
        records.sort(key=lambda r: r.confidence_score, reverse=True)
        return records[:10]

    async def get_company_network(
        self,
        company_name: str,
        session: AsyncSession,
    ) -> dict:
        """
        Return a {nodes, edges} network for a company.

        Nodes: the company node + all persons with employment records there.
        Edges: person→company employment edges + person↔person relationship edges.
        """
        name_lower = company_name.lower().strip()

        emp_stmt = select(EmploymentHistory).where(
            func.lower(EmploymentHistory.employer_name).contains(name_lower)
        )
        emp_result = await session.execute(emp_stmt)
        emp_rows: list[EmploymentHistory] = list(emp_result.scalars().all())

        person_ids = list({str(r.person_id) for r in emp_rows if r.person_id})

        person_rows: list[Person] = []
        if person_ids:
            p_stmt = select(Person).where(Person.id.in_([uuid.UUID(pid) for pid in person_ids]))
            p_result = await session.execute(p_stmt)
            person_rows = list(p_result.scalars().all())

        company_node_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, name_lower))
        nodes_dict: dict[str, dict] = {
            company_node_id: {
                "id": company_node_id,
                "type": "company",
                "label": company_name,
                "risk_score": 0.0,
            }
        }
        edges: list[dict] = []

        person_map: dict[str, Person] = {str(p.id): p for p in person_rows}

        for row in emp_rows:
            pid = str(row.person_id) if row.person_id else None
            if not pid:
                continue
            person = person_map.get(pid)
            label = person.full_name if person else pid
            risk = (person.default_risk_score or 0.0) if person else 0.0

            if pid not in nodes_dict:
                nodes_dict[pid] = {"id": pid, "type": "person", "label": label, "risk_score": risk}

            edge_type = "officer" if row.job_title else "employee"
            edges.append(
                {
                    "source": pid,
                    "target": company_node_id,
                    "type": edge_type,
                    "confidence": 0.9 if row.is_current else 0.6,
                }
            )

        # Add person↔person relationship edges among the company members
        if len(person_ids) > 1:
            pid_uuids = [uuid.UUID(p) for p in person_ids]
            rel_stmt = select(Relationship).where(
                Relationship.person_a_id.in_(pid_uuids),
                Relationship.person_b_id.in_(pid_uuids),
            )
            rel_result = await session.execute(rel_stmt)
            rel_rows: list[Relationship] = list(rel_result.scalars().all())

            for rel in rel_rows:
                edges.append(
                    {
                        "source": str(rel.person_a_id),
                        "target": str(rel.person_b_id),
                        "type": rel.rel_type,
                        "confidence": rel.score,
                    }
                )

        return {"nodes": list(nodes_dict.values()), "edges": edges}

    async def get_person_companies(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> list[CompanyRecord]:
        """Return all companies a person is associated with via EmploymentHistory."""
        pid_uuid = uuid.UUID(person_id)

        stmt = select(EmploymentHistory).where(
            EmploymentHistory.person_id == pid_uuid,
            EmploymentHistory.employer_name.isnot(None),
        )
        result = await session.execute(stmt)
        rows: list[EmploymentHistory] = list(result.scalars().all())

        if not rows:
            return []

        # Fetch the person once for officer resolution
        p_stmt = select(Person).where(Person.id == pid_uuid)
        p_result = await session.execute(p_stmt)
        person = p_result.scalar_one_or_none()
        person_rows = [person] if person else []

        records: list[CompanyRecord] = []
        for row in rows:
            employer = row.employer_name or ""
            record = _build_record_from_rows(employer, [row], person_rows)
            records.append(record)

        records.sort(key=lambda r: r.confidence_score, reverse=True)
        return records
