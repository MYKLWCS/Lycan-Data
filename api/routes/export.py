"""Data export endpoints."""

import csv
import io
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.models.identifier import Identifier
from shared.models.person import Alias, Person
from shared.models.social_profile import SocialProfile

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{person_id}/json")
async def export_person_json(person_id: uuid.UUID, db: AsyncSession = DbDep):
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    aliases = (await db.scalars(select(Alias).where(Alias.person_id == person_id))).all()
    identifiers = (
        await db.scalars(select(Identifier).where(Identifier.person_id == person_id))
    ).all()
    socials = (
        await db.scalars(select(SocialProfile).where(SocialProfile.person_id == person_id))
    ).all()
    payload = {
        "person": {
            "id": str(person.id),
            "full_name": person.full_name,
            "date_of_birth": str(person.date_of_birth) if person.date_of_birth else None,
            "nationality": person.nationality,
            "default_risk_score": person.default_risk_score,
            "enrichment_score": person.enrichment_score,
            "meta": person.meta,
        },
        "aliases": [
            {"alias": a.alias, "alias_type": a.alias_type, "confidence": a.confidence}
            for a in aliases
        ],
        "identifiers": [
            {"type": i.type, "value": i.value, "normalized_value": i.normalized_value}
            for i in identifiers
        ],
        "social_profiles": [
            {"platform": s.platform, "handle": s.handle, "url": s.url} for s in socials
        ],
    }
    content = json.dumps(payload, indent=2, default=str)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=person_{person_id}.json"},
    )


@router.get("/{person_id}/csv")
async def export_person_csv(person_id: uuid.UUID, db: AsyncSession = DbDep):
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    identifiers = (
        await db.scalars(select(Identifier).where(Identifier.person_id == person_id))
    ).all()
    socials = (
        await db.scalars(select(SocialProfile).where(SocialProfile.person_id == person_id))
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "value", "platform", "confidence"])
    for i in identifiers:
        writer.writerow(["identifier", i.value, i.type or "", i.confidence or ""])
    for s in socials:
        writer.writerow(["social", s.handle or "", s.platform, s.follower_count or ""])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.read().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=person_{person_id}.csv"},
    )
