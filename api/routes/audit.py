"""Audit endpoints — expose SystemAudit snapshots and per-entity drill-downs."""

from __future__ import annotations

import logging
from datetime import timezone, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import select, text

from api.deps import DbDep
from shared.models.audit import SystemAudit
from shared.models.person import Person

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------


def _audit_to_dict(row: SystemAudit) -> dict:
    return {
        "id": str(row.id),
        "run_at": row.run_at.isoformat() if row.run_at else None,
        "persons_total": row.persons_total,
        "persons_low_coverage": row.persons_low_coverage,
        "persons_stale": row.persons_stale,
        "persons_conflict": row.persons_conflict,
        "crawlers_total": row.crawlers_total,
        "crawlers_healthy": row.crawlers_healthy,
        "crawlers_degraded": row.crawlers_degraded,
        "tags_assigned_today": row.tags_assigned_today,
        "merges_today": row.merges_today,
        "persons_ingested_today": row.persons_ingested_today,
        "meta": row.meta,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _person_to_slim(p: Person) -> dict:
    return {
        "id": str(p.id),
        "full_name": p.full_name,
        "last_scraped_at": p.last_scraped_at.isoformat() if p.last_scraped_at else None,
        "meta": p.meta,
    }


# ---------------------------------------------------------------------------
# GET /audit/latest
# ---------------------------------------------------------------------------


@router.get("/latest")
async def audit_latest(session=DbDep):
    """Return the most recent SystemAudit snapshot."""
    result = await session.execute(select(SystemAudit).order_by(SystemAudit.run_at.desc()).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No audit runs found")
    return _audit_to_dict(row)


# ---------------------------------------------------------------------------
# POST /audit/run
# ---------------------------------------------------------------------------


async def _trigger_audit() -> None:
    from modules.audit.audit_daemon import AuditDaemon

    daemon = AuditDaemon()
    try:
        await daemon._run_audit()
    except Exception:  # pragma: no cover
        logger.exception("Manual audit trigger failed")


@router.post("/run", status_code=202)
async def audit_run(background_tasks: BackgroundTasks):
    """Trigger an immediate audit run (non-blocking)."""
    background_tasks.add_task(_trigger_audit)
    return {"status": "triggered", "message": "Audit run queued as background task"}


# ---------------------------------------------------------------------------
# GET /audit/history
# ---------------------------------------------------------------------------


@router.get("/history")
async def audit_history(
    limit: int = Query(default=30, ge=1, le=200),
    session=DbDep,
):
    """Return the last N audit runs ordered newest first."""
    result = await session.execute(
        select(SystemAudit).order_by(SystemAudit.run_at.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return [_audit_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /audit/crawlers
# ---------------------------------------------------------------------------


@router.get("/crawlers")
async def audit_crawlers(session=DbDep):
    """Per-crawler health breakdown for the last 24 hours."""
    result = await session.execute(
        text(
            "SELECT job_type, "
            "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS found_count, "
            "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS error_count, "
            "COUNT(*) AS total_jobs "
            "FROM crawl_jobs "
            "WHERE created_at >= NOW() - INTERVAL '24 hours' "
            "GROUP BY job_type "
            "ORDER BY job_type"
        )
    )
    rows = result.mappings().all()

    crawlers = []
    for row in rows:
        found = int(row["found_count"] or 0)
        errors = int(row["error_count"] or 0)
        total = found + errors
        rate = (found / total) if total > 0 else None
        crawlers.append(
            {
                "name": row["job_type"],
                "found_count": found,
                "error_count": errors,
                "total_jobs": int(row["total_jobs"] or 0),
                "success_rate": round(rate, 4) if rate is not None else None,
                "degraded": rate == 0.0 if rate is not None else False,
            }
        )

    # Sort: degraded first, then by success_rate descending
    crawlers.sort(key=lambda c: (not c["degraded"], -(c["success_rate"] or 0)))
    return {"crawlers": crawlers, "count": len(crawlers)}


# ---------------------------------------------------------------------------
# GET /audit/persons/stale
# ---------------------------------------------------------------------------


@router.get("/persons/stale")
async def audit_persons_stale(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session=DbDep,
):
    """Return persons not scraped in the last 30 days (excluding merged)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    result = await session.execute(
        select(Person)
        .where(
            Person.merged_into.is_(None),
            Person.last_scraped_at < cutoff,
        )
        .order_by(Person.last_scraped_at.asc())
        .offset(offset)
        .limit(limit)
    )
    persons = result.scalars().all()
    return [_person_to_slim(p) for p in persons]


# ---------------------------------------------------------------------------
# GET /audit/persons/low-coverage
# ---------------------------------------------------------------------------


@router.get("/persons/low-coverage")
async def audit_persons_low_coverage(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session=DbDep,
):
    """Return persons with coverage_pct < 50 (excluding merged)."""
    result = await session.execute(
        select(Person)
        .where(
            Person.merged_into.is_(None),
            text("(persons.meta->'coverage'->>'pct')::numeric < 50"),
        )
        .order_by(text("(persons.meta->'coverage'->>'pct')::numeric ASC NULLS FIRST"))
        .offset(offset)
        .limit(limit)
    )
    persons = result.scalars().all()
    return [_person_to_slim(p) for p in persons]
