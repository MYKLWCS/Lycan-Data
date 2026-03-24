"""Marketing tags and consumer segmentation API routes."""
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _model_to_dict
from modules.enrichers.marketing_tags import MarketingTagsEngine
from shared.models.marketing import ConsumerSegment, MarketingTag
from shared.models.person import Person

router = APIRouter()
logger = logging.getLogger(__name__)

_engine = MarketingTagsEngine()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{person_id}/tag")
async def tag_person(person_id: str, session: AsyncSession = DbDep):
    """Run MarketingTagsEngine on the person and persist results to DB."""
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {person_id!r}")

    try:
        tag_results = await _engine.tag_person(str(uid), session)
    except Exception as exc:
        logger.exception("Tagging failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    # Upsert each tag result into the marketing_tags table
    for result in tag_results:
        existing = (await session.execute(
            select(MarketingTag).where(
                MarketingTag.person_id == uid,
                MarketingTag.tag == result.tag,
            )
        )).scalars().first()

        if existing:
            existing.confidence = result.confidence
            existing.reasoning = result.reasoning
            existing.scored_at = result.scored_at
        else:
            session.add(MarketingTag(
                person_id=uid,
                tag=result.tag,
                confidence=result.confidence,
                reasoning=result.reasoning,
                scored_at=result.scored_at,
            ))

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(500, "Failed to persist tags") from exc

    return {
        "person_id": person_id,
        "tags": [
            {
                "tag": r.tag,
                "confidence": r.confidence,
                "reasoning": r.reasoning,
                "scored_at": r.scored_at.isoformat() if r.scored_at else None,
            }
            for r in tag_results
        ],
        "tag_count": len(tag_results),
    }


@router.get("/{person_id}/tags")
async def get_tags(person_id: str, session: AsyncSession = DbDep):
    """Return all MarketingTag rows for the person."""
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {person_id!r}")

    rows = (await session.execute(
        select(MarketingTag).where(MarketingTag.person_id == uid)
    )).scalars().all()

    return {
        "person_id": person_id,
        "tags": [_model_to_dict(r) for r in rows],
    }


@router.get("/tags/by-tag/{tag_name}")
async def get_persons_by_tag(
    tag_name: str,
    threshold: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(50, le=500),
    session: AsyncSession = DbDep,
):
    """Return persons who have a specific tag with confidence >= threshold."""
    rows = (await session.execute(
        select(MarketingTag, Person.full_name)
        .join(Person, Person.id == MarketingTag.person_id)
        .where(
            MarketingTag.tag == tag_name,
            MarketingTag.confidence >= threshold,
        )
        .limit(limit)
    )).all()

    return {
        "tag": tag_name,
        "persons": [
            {
                "person_id": str(row.MarketingTag.person_id),
                "full_name": row.full_name,
                "confidence": row.MarketingTag.confidence,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.get("/{person_id}/borrower-profile")
async def get_borrower_profile(person_id: str, session: AsyncSession = DbDep):
    """Return latest ConsumerSegment rows for the person (capped at 50)."""
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {person_id!r}")

    rows = (await session.execute(
        select(ConsumerSegment)
        .where(ConsumerSegment.person_id == uid)
        .order_by(ConsumerSegment.created_at.desc())
        .limit(50)
    )).scalars().all()

    return {
        "person_id": person_id,
        "segments": [_model_to_dict(r) for r in rows],
    }
