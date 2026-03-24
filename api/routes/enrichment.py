"""Enrichment pipeline API routes."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator

router = APIRouter()
logger = logging.getLogger(__name__)

_orchestrator = EnrichmentOrchestrator()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_uuid(value: str) -> uuid.UUID:
    """Parse and return a UUID, raising HTTP 400 on failure."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {value!r}")


def _report_to_dict(report) -> dict:
    return {
        "person_id": report.person_id,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "total_duration_ms": report.total_duration_ms,
        "ok_count": report.ok_count,
        "error_count": report.error_count,
        "steps": [
            {
                "enricher": s.enricher,
                "status": s.status,
                "detail": s.detail,
                "duration_ms": s.duration_ms,
            }
            for s in report.steps
        ],
    }


async def _background_enrich(person_id: str) -> None:
    from shared.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            await _orchestrator.enrich_person(person_id, session)
            await session.commit()
        except Exception:
            logger.exception("Background enrichment failed person_id=%s", person_id)
            await session.rollback()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/{person_id}/enrich")
async def enrich_person(person_id: str, session: AsyncSession = DbDep):
    """
    Run the full enrichment pipeline for a person synchronously.
    Returns an EnrichmentReport with per-step results.
    """
    _validate_uuid(person_id)
    try:
        report = await _orchestrator.enrich_person(person_id, session)
        return _report_to_dict(report)
    except Exception:
        logger.exception("Enrichment pipeline failed for person_id=%s", person_id)
        raise HTTPException(status_code=500, detail="Enrichment pipeline failed")


@router.post("/{person_id}/enrich/background")
async def enrich_person_background(
    person_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = DbDep,
):
    """
    Queue the full enrichment pipeline for a person as a background task.
    Returns immediately with a queued status.
    """
    _validate_uuid(person_id)
    try:
        background_tasks.add_task(_background_enrich, person_id)
        return {
            "person_id": person_id,
            "status": "queued",
            "message": "Enrichment started in background",
        }
    except Exception:
        logger.exception("Failed to queue background enrichment for person_id=%s", person_id)
        raise HTTPException(status_code=500, detail="Failed to queue enrichment")
