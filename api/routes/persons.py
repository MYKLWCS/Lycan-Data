import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.models.person import Person
from shared.models.identifier import Identifier
from shared.models.social_profile import SocialProfile

router = APIRouter()


def _person_summary(p: Person) -> dict:
    return {
        "id": str(p.id),
        "full_name": p.full_name,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "default_risk_score": p.default_risk_score,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _model_to_dict(obj) -> dict:
    """Serialize a SQLAlchemy model row to a plain dict, converting UUIDs and dates."""
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if val is None:
            out[col.name] = None
        elif hasattr(val, "isoformat"):
            out[col.name] = val.isoformat()
        else:
            out[col.name] = str(val) if isinstance(val, uuid.UUID) else val
    return out


@router.get("")
async def list_persons(
    limit: int = Query(20, le=100),
    offset: int = 0,
    risk_tier: str | None = None,
    session: AsyncSession = DbDep,
):
    q = select(Person).order_by(Person.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(q)
    persons = result.scalars().all()
    return {
        "persons": [_person_summary(p) for p in persons],
        "total": len(persons),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{person_id}")
async def get_person(person_id: str, session: AsyncSession = DbDep):
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    idents = (
        await session.execute(select(Identifier).where(Identifier.person_id == p.id))
    ).scalars().all()

    profiles = (
        await session.execute(select(SocialProfile).where(SocialProfile.person_id == p.id))
    ).scalars().all()

    return {
        "id": str(p.id),
        "full_name": p.full_name,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "gender": p.gender,
        "nationality": p.nationality,
        "primary_language": p.primary_language,
        "bio": p.bio,
        "profile_image_url": p.profile_image_url,
        "relationship_score": p.relationship_score,
        "behavioural_risk": p.behavioural_risk,
        "darkweb_exposure": p.darkweb_exposure,
        "default_risk_score": p.default_risk_score,
        "identifiers": [
            {"type": i.type, "value": i.value, "confidence": i.confidence, "is_primary": i.is_primary}
            for i in idents
        ],
        "social_profiles": [
            {
                "platform": s.platform,
                "handle": s.handle,
                "display_name": s.display_name,
                "followers": s.follower_count,
                "is_verified": s.is_verified,
                "is_private": s.is_private,
            }
            for s in profiles
        ],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/{person_id}/identifiers")
async def get_identifiers(person_id: str, session: AsyncSession = DbDep):
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    idents = (
        await session.execute(select(Identifier).where(Identifier.person_id == uid))
    ).scalars().all()

    return {"person_id": person_id, "identifiers": [_model_to_dict(i) for i in idents]}


@router.get("/{person_id}/social")
async def get_social_profiles(person_id: str, session: AsyncSession = DbDep):
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    profiles = (
        await session.execute(select(SocialProfile).where(SocialProfile.person_id == uid))
    ).scalars().all()

    return {"person_id": person_id, "social_profiles": [_model_to_dict(s) for s in profiles]}


@router.get("/{person_id}/certificate")
async def get_certificate(person_id: str, session: AsyncSession = DbDep):
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    idents = (
        await session.execute(select(Identifier).where(Identifier.person_id == uid))
    ).scalars().all()

    profiles = (
        await session.execute(select(SocialProfile).where(SocialProfile.person_id == uid))
    ).scalars().all()

    from modules.enrichers.certification import certify_person

    person_data = {
        "full_name": p.full_name,
        "dob": p.date_of_birth,
        "phone": next((i.value for i in idents if i.type == "phone"), None),
        "email": next((i.value for i in idents if i.type == "email"), None),
        "instagram": next((s.handle for s in profiles if s.platform == "instagram"), None),
        "twitter": next((s.handle for s in profiles if s.platform == "twitter"), None),
        "default_risk_score": p.default_risk_score,
    }

    quality = {
        "source_count": len(profiles) + len(idents),
        "avg_freshness": 0.8,
        "avg_reliability": 0.65,
        "corroborated_fields": sum(1 for v in person_data.values() if v is not None),
        "conflicts": 0,
    }

    cert = certify_person(person_id, person_data, quality)
    return {
        "person_id": person_id,
        "grade": cert.grade.value,
        "overall_score": round(cert.overall_score, 3),
        "source_count": cert.source_count,
        "covered_categories": cert.covered_categories,
        "missing_categories": cert.missing_categories,
        "coverage_score": round(cert.coverage_score, 3),
        "improvement_actions": cert.improvement_actions,
        "certified_at": cert.certified_at,
    }


@router.get("/{person_id}/report")
async def get_report(person_id: str, session: AsyncSession = DbDep):
    """Full comprehensive report joining all available tables."""
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    from shared.models.person import Alias
    from shared.models.address import Address
    from shared.models.employment import EmploymentHistory
    from shared.models.darkweb import DarkwebMention
    from shared.models.watchlist import WatchlistMatch

    async def _fetch(model):
        r = await session.execute(select(model).where(model.person_id == uid))
        return r.scalars().all()

    idents = await _fetch(Identifier)
    profiles = await _fetch(SocialProfile)
    aliases = await _fetch(Alias)
    addresses = await _fetch(Address)
    employment = await _fetch(EmploymentHistory)
    darkweb = await _fetch(DarkwebMention)
    watchlist = await _fetch(WatchlistMatch)

    return {
        "person": _model_to_dict(p),
        "aliases": [_model_to_dict(a) for a in aliases],
        "identifiers": [_model_to_dict(i) for i in idents],
        "social_profiles": [_model_to_dict(s) for s in profiles],
        "addresses": [_model_to_dict(a) for a in addresses],
        "employment": [_model_to_dict(e) for e in employment],
        "darkweb_mentions": [_model_to_dict(d) for d in darkweb],
        "watchlist_matches": [_model_to_dict(w) for w in watchlist],
        "summary": {
            "identifier_count": len(idents),
            "alias_count": len(aliases),
            "platform_count": len(profiles),
            "address_count": len(addresses),
            "employment_count": len(employment),
            "darkweb_hits": len(darkweb),
            "watchlist_hits": len(watchlist),
        },
    }


@router.patch("/{person_id}")
async def update_person(person_id: str, updates: dict, session: AsyncSession = DbDep):
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    ALLOWED_FIELDS = {
        "full_name", "gender", "nationality", "primary_language",
        "bio", "profile_image_url", "meta",
    }
    for field, value in updates.items():
        if field in ALLOWED_FIELDS:
            setattr(p, field, value)

    await session.commit()
    return {"message": "Person updated", "person_id": person_id}


@router.delete("/{person_id}")
async def delete_person(person_id: str, session: AsyncSession = DbDep):
    from datetime import datetime, timezone

    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, "Invalid person_id — must be a UUID")

    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")

    # Soft delete — set deleted_at if the field exists, otherwise hard delete
    if hasattr(p, "deleted_at"):
        p.deleted_at = datetime.now(timezone.utc)
        await session.commit()
        return {"message": "Person soft-deleted", "person_id": person_id}
    else:
        await session.delete(p)
        await session.commit()
        return {"message": "Person deleted", "person_id": person_id}
