"""
Discovery / Review Tab API routes.

GET  /discovery/sources          — list review queue (pending by default)
GET  /discovery/sources/{id}     — get single source
POST /discovery/run              — trigger open-discovery run
POST /discovery/sources/{id}/approve   — approve source
POST /discovery/sources/{id}/reject    — reject source
POST /discovery/sources/{id}/build-crawler — generate crawler template
POST /discovery/sources/bulk     — bulk approve / reject
GET  /discovery/stats            — self-improvement stats
"""

from __future__ import annotations

import logging
import uuid
from datetime import timezone, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import asc, desc, func, select, update

from api.deps import DbDep
from modules.discovery.crawler_builder import build_template
from modules.discovery.orchestrator import run_discovery
from shared.models.discovery import DiscoveredSource

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Serialiser ─────────────────────────────────────────────────────────────────

def _source_dict(s: DiscoveredSource) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "url": s.url,
        "category": s.category,
        "discovered_by": s.discovered_by,
        "discovery_query": s.discovery_query,
        "data_quality_estimate": s.data_quality_estimate,
        "legal_risk": s.legal_risk,
        "data_types": s.data_types or [],
        "proposed_pattern": s.proposed_pattern,
        "raw_context": s.raw_context,
        "status": s.status,
        "reliability_tier": s.reliability_tier,
        "approval_notes": s.approval_notes,
        "approved_by": s.approved_by,
        "approved_at": s.approved_at.isoformat() if s.approved_at else None,
        "rejected_at": s.rejected_at.isoformat() if s.rejected_at else None,
        "crawler_template": s.crawler_template,
        "crawler_deployed": s.crawler_deployed,
        "crawl_success_rate": s.crawl_success_rate,
        "total_records_harvested": s.total_records_harvested,
        "is_high_value": s.is_high_value,
        "created_at": s.created_at.isoformat(),
    }


def _get_or_404(session, source_id: str):
    """Helper used in sync context — callers must await the DB get separately."""
    try:
        return uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(400, "Invalid source_id — must be a UUID")


# ── List review queue ──────────────────────────────────────────────────────────

@router.get("/sources")
async def list_sources(
    status: str = Query("pending", pattern="^(pending|approved|rejected|all)$"),
    category: str | None = None,
    discovered_by: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal["quality", "created", "name"] = "quality",
    session=DbDep,
):
    q = select(DiscoveredSource)

    if status != "all":
        q = q.where(DiscoveredSource.status == status)
    if category:
        q = q.where(DiscoveredSource.category == category)
    if discovered_by:
        q = q.where(DiscoveredSource.discovered_by == discovered_by)

    if sort == "quality":
        q = q.order_by(
            desc(DiscoveredSource.is_high_value),
            desc(DiscoveredSource.data_quality_estimate),
        )
    elif sort == "created":
        q = q.order_by(desc(DiscoveredSource.created_at))
    else:
        q = q.order_by(asc(DiscoveredSource.name))

    total_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(total_q)).scalar_one()

    rows = (await session.execute(q.offset(offset).limit(limit))).scalars().all()
    return {
        "sources": [_source_dict(s) for s in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ── Get single source ──────────────────────────────────────────────────────────

@router.get("/sources/{source_id}")
async def get_source(source_id: str, session=DbDep):
    uid = _get_or_404(session, source_id)
    row = await session.get(DiscoveredSource, uid)
    if not row:
        raise HTTPException(404, "Source not found")
    return _source_dict(row)


# ── Trigger discovery run ──────────────────────────────────────────────────────

class RunDiscoveryRequest(BaseModel):
    query: str
    tools: list[str] | None = None  # None = all tools


@router.post("/run", status_code=202)
async def trigger_discovery(
    body: RunDiscoveryRequest,
    background_tasks: BackgroundTasks,
    session=DbDep,
):
    if not body.query.strip():
        raise HTTPException(400, "query must not be empty")

    async def _bg():
        from shared.db import AsyncSessionLocal
        async with AsyncSessionLocal() as bg_session:
            try:
                summary = await run_discovery(
                    body.query.strip(),
                    bg_session,
                    tool_names=body.tools,
                )
                logger.info("Background discovery done: %s", summary)
            except Exception as exc:
                logger.error("Background discovery failed: %s", exc)

    background_tasks.add_task(_bg)
    return {
        "status": "accepted",
        "message": f"Discovery run queued for query: {body.query!r}",
        "tools": body.tools or "all",
    }


# ── Approve source ─────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    notes: str = ""
    reliability_tier: str = "C"
    data_types: list[str] | None = None
    approved_by: str = "operator"


@router.post("/sources/{source_id}/approve", status_code=200)
async def approve_source(source_id: str, body: ApproveRequest, session=DbDep):
    uid = _get_or_404(session, source_id)
    row: DiscoveredSource | None = await session.get(DiscoveredSource, uid)
    if not row:
        raise HTTPException(404, "Source not found")
    if row.status == "approved":
        raise HTTPException(409, "Source already approved")

    now = datetime.now(timezone.utc)
    row.status = "approved"
    row.approval_notes = body.notes or None
    row.reliability_tier = body.reliability_tier.upper()[:2]
    row.approved_by = body.approved_by
    row.approved_at = now
    if body.data_types:
        row.data_types = body.data_types

    await session.commit()
    await session.refresh(row)
    return _source_dict(row)


# ── Reject source ──────────────────────────────────────────────────────────────

class RejectRequest(BaseModel):
    notes: str = ""


@router.post("/sources/{source_id}/reject", status_code=200)
async def reject_source(source_id: str, body: RejectRequest, session=DbDep):
    uid = _get_or_404(session, source_id)
    row: DiscoveredSource | None = await session.get(DiscoveredSource, uid)
    if not row:
        raise HTTPException(404, "Source not found")
    if row.status == "rejected":
        raise HTTPException(409, "Source already rejected")

    row.status = "rejected"
    row.approval_notes = body.notes or None
    row.rejected_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(row)
    return _source_dict(row)


# ── Build crawler template ─────────────────────────────────────────────────────

@router.post("/sources/{source_id}/build-crawler", status_code=200)
async def build_crawler(source_id: str, session=DbDep):
    uid = _get_or_404(session, source_id)
    row: DiscoveredSource | None = await session.get(DiscoveredSource, uid)
    if not row:
        raise HTTPException(404, "Source not found")
    if row.status != "approved":
        raise HTTPException(400, "Source must be approved before building a crawler")

    template = build_template(
        name=row.name,
        url=row.url,
        category=row.category,
        data_types=row.data_types,
        proposed_pattern=row.proposed_pattern,
        reliability_tier=row.reliability_tier,
    )

    row.crawler_template = template
    await session.commit()
    await session.refresh(row)

    return {
        "source_id": str(row.id),
        "template": template,
        "message": (
            f"Crawler template generated. Write to {template['file_path']} "
            "to deploy it."
        ),
    }


# ── Bulk approve / reject ──────────────────────────────────────────────────────

class BulkActionRequest(BaseModel):
    source_ids: list[str]
    action: Literal["approve", "reject"]
    notes: str = ""
    reliability_tier: str = "C"


@router.post("/sources/bulk", status_code=200)
async def bulk_action(body: BulkActionRequest, session=DbDep):
    if not body.source_ids:
        raise HTTPException(400, "source_ids must not be empty")
    if len(body.source_ids) > 200:
        raise HTTPException(400, "Max 200 sources per bulk operation")

    uids: list[uuid.UUID] = []
    for sid in body.source_ids:
        try:
            uids.append(uuid.UUID(sid))
        except ValueError:
            raise HTTPException(400, f"Invalid UUID: {sid!r}")

    now = datetime.now(timezone.utc)
    if body.action == "approve":
        await session.execute(
            update(DiscoveredSource)
            .where(DiscoveredSource.id.in_(uids))
            .values(
                status="approved",
                approval_notes=body.notes or None,
                reliability_tier=body.reliability_tier.upper()[:2],
                approved_at=now,
            )
        )
    else:
        await session.execute(
            update(DiscoveredSource)
            .where(DiscoveredSource.id.in_(uids))
            .values(
                status="rejected",
                approval_notes=body.notes or None,
                rejected_at=now,
            )
        )

    await session.commit()
    return {
        "action": body.action,
        "updated": len(uids),
        "source_ids": [str(u) for u in uids],
    }


# ── Self-improvement stats ─────────────────────────────────────────────────────

@router.get("/stats")
async def discovery_stats(session=DbDep):
    total = (
        await session.execute(select(func.count()).select_from(DiscoveredSource))
    ).scalar_one()

    by_status = {}
    for status_val in ("pending", "approved", "rejected"):
        count = (
            await session.execute(
                select(func.count()).where(DiscoveredSource.status == status_val)
            )
        ).scalar_one()
        by_status[status_val] = count

    high_value = (
        await session.execute(
            select(func.count()).where(DiscoveredSource.is_high_value.is_(True))
        )
    ).scalar_one()

    by_tool_q = (
        await session.execute(
            select(DiscoveredSource.discovered_by, func.count())
            .group_by(DiscoveredSource.discovered_by)
            .order_by(desc(func.count()))
        )
    )
    by_tool = {row[0]: row[1] for row in by_tool_q}

    by_category_q = (
        await session.execute(
            select(DiscoveredSource.category, func.count())
            .group_by(DiscoveredSource.category)
            .order_by(desc(func.count()))
        )
    )
    by_category = {(row[0] or "unknown"): row[1] for row in by_category_q}

    return {
        "total": total,
        "by_status": by_status,
        "high_value": high_value,
        "by_tool": by_tool,
        "by_category": by_category,
    }
