"""People Builder API routes — universal discovery engine."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _serialize
from modules.builder.discovery_engine import people_builder
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.builder_job import BuilderJob, BuilderJobPerson
from shared.models.person import Person

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request / Response schemas ─────────────────────────────────────────────


class DiscoverRequest(BaseModel):
    location: str | None = None
    state: str | None = None
    country: str | None = None
    income_range: dict[str, float] | None = None
    age_range: dict[str, int] | None = None
    has_vehicle: bool | None = None
    vehicle_value_min: float | None = None
    property_owner: bool | None = None
    property_value_range: dict[str, float] | None = None
    has_social_media: bool | None = None
    specific_platform: str | None = None
    risk_tier: str | None = None
    tags: list[str] | None = None
    employer: str | None = None
    industry: str | None = None
    education_level: str | None = None
    marital_status: str | None = None
    has_criminal_record: bool | None = None
    has_bankruptcy: bool | None = None
    credit_score_range: dict[str, int] | None = None
    keywords: str | None = None
    seed_list: list[str] | None = None
    max_results: int = Field(default=100, ge=1, le=10000)


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/discover")
async def start_discovery(req: DiscoverRequest):
    """Start a people discovery job. Returns job_id immediately."""
    criteria = req.model_dump(exclude_none=True, exclude={"max_results"})
    if not criteria:
        raise HTTPException(400, "At least one search criterion is required")

    try:
        job_id = await people_builder.start_discovery(
            criteria=criteria,
            max_results=req.max_results,
        )
    except Exception as exc:
        logger.exception("Failed to start discovery")
        raise HTTPException(500, "Failed to start discovery job") from exc

    return {"job_id": job_id, "status": "pending", "message": "Discovery job started"}


@router.get("/{job_id}/progress")
async def job_progress(job_id: str):
    """SSE stream of progress events for a builder job."""
    import asyncio
    import json

    async def event_stream():
        try:
            pubsub = event_bus.redis.pubsub()
            await pubsub.subscribe(event_bus.CHANNELS.get("progress", "lycan:progress"))
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        if data.get("job_id") == job_id:
                            yield f"data: {json.dumps(data)}\n\n"
                            if data.get("phase") in ("complete", "error"):
                                break
                    except (json.JSONDecodeError, TypeError):
                        pass
        except Exception:
            yield f"data: {json.dumps({'phase': 'error', 'message': 'SSE connection failed'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}/results")
async def job_results(
    job_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = DbDep,
):
    """Paginated results for a builder job with enrichment scores."""
    job_uuid = uuid.UUID(job_id)

    # Get job
    job_result = await session.execute(
        select(BuilderJob).where(BuilderJob.id == job_uuid)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    # Get linked persons that passed filtering
    stmt = (
        select(BuilderJobPerson, Person)
        .join(Person, Person.id == BuilderJobPerson.person_id)
        .where(
            BuilderJobPerson.job_id == job_uuid,
            BuilderJobPerson.phase.in_(["filtered_in", "built", "expanded"]),
        )
        .order_by(BuilderJobPerson.enrichment_score.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = result.all()

    persons = []
    for link, person in rows:
        persons.append({
            "person_id": str(person.id),
            "full_name": person.full_name,
            "date_of_birth": person.date_of_birth.isoformat() if person.date_of_birth else None,
            "gender": person.gender,
            "enrichment_score": person.enrichment_score or 0,
            "risk_score": person.default_risk_score or 0,
            "alt_credit_score": person.alt_credit_score,
            "marketing_tags": person.marketing_tags_list or [],
            "phase": link.phase,
            "match_score": link.match_score,
        })

    return {
        "job_id": job_id,
        "status": job.status,
        "results": persons,
        "count": len(persons),
        "offset": offset,
        "total_filtered": job.filtered_count,
    }


@router.get("/{job_id}/stats")
async def job_stats(job_id: str, session: AsyncSession = DbDep):
    """Stats for a builder job."""
    job_result = await session.execute(
        select(BuilderJob).where(BuilderJob.id == uuid.UUID(job_id))
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": job_id,
        "status": job.status,
        "discovered_count": job.discovered_count,
        "built_count": job.built_count,
        "filtered_count": job.filtered_count,
        "expanded_count": job.expanded_count,
        "relationships_mapped": job.relationships_mapped,
        "max_results": job.max_results,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        "criteria": job.criteria,
    }


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = DbDep,
):
    """List all builder jobs."""
    stmt = select(BuilderJob).order_by(BuilderJob.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(BuilderJob.status == status)
    result = await session.execute(stmt)
    jobs = result.scalars().all()

    return {
        "jobs": [
            {
                "job_id": str(j.id),
                "status": j.status,
                "discovered_count": j.discovered_count,
                "built_count": j.built_count,
                "filtered_count": j.filtered_count,
                "max_results": j.max_results,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "criteria_summary": _criteria_summary(j.criteria),
            }
            for j in jobs
        ],
        "count": len(jobs),
        "offset": offset,
    }


@router.post("/{job_id}/expand")
async def expand_results(job_id: str, session: AsyncSession = DbDep):
    """Manually trigger deeper expansion on job results."""
    job_result = await session.execute(
        select(BuilderJob).where(BuilderJob.id == uuid.UUID(job_id))
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("complete", "expanding"):
        raise HTTPException(400, f"Cannot expand job in status: {job.status}")

    # Get filtered persons
    persons_result = await session.execute(
        select(BuilderJobPerson.person_id).where(
            BuilderJobPerson.job_id == uuid.UUID(job_id),
            BuilderJobPerson.phase == "filtered_in",
        )
    )
    person_ids = [str(r[0]) for r in persons_result.all()]

    expanded = 0
    for pid in person_ids:
        try:
            await event_bus.publish("graph", {
                "event": "expand_relationships",
                "person_id": pid,
                "depth": 3,
                "source": "builder_manual_expand",
            })
            expanded += 1
        except Exception:
            pass

    return {"expanded": expanded, "message": f"Queued expansion for {expanded} persons"}


@router.delete("/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running builder job."""
    cancelled = await people_builder.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(404, "Job not found or already completed")
    return {"job_id": job_id, "status": "cancelled"}


def _criteria_summary(criteria: dict) -> str:
    """Build a short human-readable summary of criteria."""
    parts = []
    if criteria.get("location"):
        parts.append(f"location: {criteria['location']}")
    if criteria.get("employer"):
        parts.append(f"employer: {criteria['employer']}")
    if criteria.get("keywords"):
        parts.append(f"keywords: {criteria['keywords']}")
    if criteria.get("seed_list"):
        parts.append(f"{len(criteria['seed_list'])} seeds")
    if criteria.get("tags"):
        parts.append(f"tags: {', '.join(criteria['tags'][:3])}")
    return "; ".join(parts) if parts else "custom criteria"
