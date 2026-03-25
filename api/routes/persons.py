"""
Persons API — CRUD, reporting, deduplication, and merge endpoints.
"""

import uuid
from datetime import UTC
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.models.address import Address
from shared.models.criminal import CriminalRecord
from shared.models.identifier import Identifier
from shared.models.identifier_history import IdentifierHistory
from shared.models.identity_document import CreditProfile, IdentityDocument
from shared.models.person import Alias, Person
from shared.models.social_profile import SocialProfile

router = APIRouter()

# ── Serialization helpers ──────────────────────────────────────────────────────


def _model_to_dict(obj) -> dict:
    """Serialize a SQLAlchemy model row to a plain dict."""
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if val is None:
            out[col.name] = None
        elif hasattr(val, "isoformat"):
            out[col.name] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            out[col.name] = str(val)
        else:
            out[col.name] = val
    return out


def _person_summary(p: Person, addresses: list[Address] | None = None) -> dict:
    current_addr = next((a for a in (addresses or []) if a.is_current), None) or next(
        iter(addresses or []), None
    )
    return {
        "id": str(p.id),
        "full_name": p.full_name,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "default_risk_score": p.default_risk_score,
        "behavioural_risk": p.behavioural_risk,
        "darkweb_exposure": p.darkweb_exposure,
        "relationship_score": p.relationship_score,
        # Data quality
        "source_reliability": p.source_reliability,
        "composite_quality": p.composite_quality,
        "corroboration_count": p.corroboration_count,
        "verification_status": p.verification_status,
        # Location (from primary address)
        "city": current_addr.city if current_addr else None,
        "state_province": current_addr.state_province if current_addr else None,
        "country": current_addr.country if current_addr else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ── SORT config ────────────────────────────────────────────────────────────────

_SORT_COLUMNS = {
    "created_at": Person.created_at,
    "updated_at": Person.updated_at,
    "default_risk_score": Person.default_risk_score,
    "behavioural_risk": Person.behavioural_risk,
    "darkweb_exposure": Person.darkweb_exposure,
    "relationship_score": Person.relationship_score,
    "composite_quality": Person.composite_quality,
    "corroboration_count": Person.corroboration_count,
    "full_name": Person.full_name,
}


# ── List / search ──────────────────────────────────────────────────────────────


@router.get("")
async def list_persons(
    limit: int = Query(20, le=200),
    offset: int = Query(0, ge=0),
    # Sorting
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    # Risk filter
    risk_tier: str | None = None,
    # Region filter
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
    # Search
    q: str | None = None,
    session: AsyncSession = DbDep,
):
    """List persons with sort, pagination, and region/risk filtering."""
    sort_col = _SORT_COLUMNS.get(sort_by, Person.created_at)
    order_expr = sort_col.asc() if sort_dir == "asc" else sort_col.desc()

    base_q = select(Person)

    # Risk tier filter
    if risk_tier:
        tier_ranges = {
            "do_not_lend": (0.80, 1.01),
            "high_risk": (0.60, 0.80),
            "medium_risk": (0.40, 0.60),
            "low_risk": (0.20, 0.40),
            "preferred": (0.00, 0.20),
        }
        if risk_tier in tier_ranges:
            lo, hi = tier_ranges[risk_tier]
            base_q = base_q.where(
                Person.default_risk_score >= lo,
                Person.default_risk_score < hi,
            )

    # Name search
    if q:
        base_q = base_q.where(Person.full_name.ilike(f"%{q}%"))

    # Region filter — join to addresses
    if city or state or country:
        addr_sub = select(Address.person_id).distinct()
        if city:
            addr_sub = addr_sub.where(Address.city.ilike(f"%{city}%"))
        if state:
            addr_sub = addr_sub.where(Address.state_province.ilike(f"%{state}%"))
        if country:
            addr_sub = addr_sub.where(Address.country.ilike(f"%{country}%"))
        base_q = base_q.where(Person.id.in_(addr_sub))

    # Total count
    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await session.execute(count_q)).scalar_one()

    # Paginated results
    rows_q = base_q.order_by(order_expr).limit(limit).offset(offset)
    persons = (await session.execute(rows_q)).scalars().all()

    # Bulk-load addresses for persons in this page
    if persons:
        person_ids = [p.id for p in persons]
        addr_rows = (
            (await session.execute(select(Address).where(Address.person_id.in_(person_ids))))
            .scalars()
            .all()
        )
        addr_by_person: dict = {}
        for a in addr_rows:
            addr_by_person.setdefault(a.person_id, []).append(a)
    else:
        addr_by_person = {}

    return {
        "persons": [_person_summary(p, addr_by_person.get(p.id, [])) for p in persons],
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }


# ── Single person ──────────────────────────────────────────────────────────────


@router.get("/{person_id}")
async def get_person(person_id: str, session: AsyncSession = DbDep):
    uid = _parse_uuid(person_id)
    p = await session.get(Person, uid)

    # ── Redirect if this record has been merged ─────────────────────
    if p is not None and p.merged_into is not None:
        return RedirectResponse(
            url=f"/persons/{p.merged_into}",
            status_code=301,
        )

    # ── 404 if not found ────────────────────────────────────────────
    if p is None:
        raise HTTPException(404, "Person not found")

    idents = (
        (await session.execute(select(Identifier).where(Identifier.person_id == p.id)))
        .scalars()
        .all()
    )
    profiles = (
        (await session.execute(select(SocialProfile).where(SocialProfile.person_id == p.id)))
        .scalars()
        .all()
    )
    addresses = (
        (await session.execute(select(Address).where(Address.person_id == p.id))).scalars().all()
    )

    return {
        "id": str(p.id),
        "full_name": p.full_name,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "gender": p.gender,
        "nationality": p.nationality,
        "primary_language": p.primary_language,
        "bio": p.bio,
        "profile_image_url": p.profile_image_url,
        # Risk scores
        "relationship_score": p.relationship_score,
        "behavioural_risk": p.behavioural_risk,
        "darkweb_exposure": p.darkweb_exposure,
        "default_risk_score": p.default_risk_score,
        # Data quality
        "source_reliability": p.source_reliability,
        "freshness_score": p.freshness_score,
        "corroboration_count": p.corroboration_count,
        "composite_quality": p.composite_quality,
        "verification_status": p.verification_status,
        "conflict_flag": p.conflict_flag,
        # Relations
        "identifiers": [
            {
                "type": i.type,
                "value": i.value,
                "confidence": i.confidence,
                "is_primary": i.is_primary,
                "source_reliability": i.source_reliability,
                "verification_status": i.verification_status,
            }
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
                "source_reliability": s.source_reliability,
                "composite_quality": s.composite_quality,
                "last_scraped_at": s.last_scraped_at.isoformat() if s.last_scraped_at else None,
            }
            for s in profiles
        ],
        "addresses": [_model_to_dict(a) for a in addresses],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/{person_id}/identifiers")
async def get_identifiers(person_id: str, session: AsyncSession = DbDep):
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)
    idents = (
        (await session.execute(select(Identifier).where(Identifier.person_id == uid)))
        .scalars()
        .all()
    )
    return {"person_id": person_id, "identifiers": [_model_to_dict(i) for i in idents]}


@router.get("/{person_id}/social")
async def get_social_profiles(person_id: str, session: AsyncSession = DbDep):
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)
    profiles = (
        (await session.execute(select(SocialProfile).where(SocialProfile.person_id == uid)))
        .scalars()
        .all()
    )
    return {"person_id": person_id, "social_profiles": [_model_to_dict(s) for s in profiles]}


@router.get("/{person_id}/addresses")
async def get_addresses(person_id: str, session: AsyncSession = DbDep):
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)
    addresses = (
        (
            await session.execute(
                select(Address).where(Address.person_id == uid).order_by(Address.is_current.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"person_id": person_id, "addresses": [_model_to_dict(a) for a in addresses]}


@router.get("/{person_id}/certificate")
async def get_certificate(person_id: str, session: AsyncSession = DbDep):
    uid = _parse_uuid(person_id)
    p = await _require_person(session, uid)

    idents = (
        (await session.execute(select(Identifier).where(Identifier.person_id == uid)))
        .scalars()
        .all()
    )
    profiles = (
        (await session.execute(select(SocialProfile).where(SocialProfile.person_id == uid)))
        .scalars()
        .all()
    )

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
        "avg_freshness": p.freshness_score,
        "avg_reliability": p.source_reliability,
        "corroborated_fields": sum(1 for v in person_data.values() if v is not None),
        "conflicts": 1 if p.conflict_flag else 0,
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
    """Full comprehensive report joining ALL available tables for this person."""
    uid = _parse_uuid(person_id)
    p = await _require_person(session, uid)

    from shared.models.alert import Alert
    from shared.models.behavioural import BehaviouralProfile
    from shared.models.breach import BreachRecord
    from shared.models.burner import BurnerAssessment
    from shared.models.darkweb import CryptoWallet, DarkwebMention
    from shared.models.employment import EmploymentHistory
    from shared.models.media import MediaAsset
    from shared.models.watchlist import WatchlistMatch

    async def _fetch(model, order_by=None):
        q = select(model).where(model.person_id == uid)
        if order_by is not None:
            q = q.order_by(order_by)
        r = await session.execute(q)
        return r.scalars().all()

    # asyncpg does not allow concurrent queries on the same session — sequential only
    idents = await _fetch(Identifier)
    profiles = await _fetch(SocialProfile)
    aliases = await _fetch(Alias)
    addresses = await _fetch(Address)
    employment = await _fetch(EmploymentHistory)
    darkweb = await _fetch(DarkwebMention)
    watchlist = await _fetch(WatchlistMatch)
    breaches = await _fetch(BreachRecord)
    criminal = await _fetch(CriminalRecord)
    documents = await _fetch(IdentityDocument)
    credit = await _fetch(CreditProfile)
    history = await _fetch(IdentifierHistory)
    behavioural = await _fetch(BehaviouralProfile)
    # BurnerAssessment links to Identifier (not person) — join via identifiers
    ident_ids = [i.id for i in idents]
    if ident_ids:
        b_res = await session.execute(
            select(BurnerAssessment).where(BurnerAssessment.identifier_id.in_(ident_ids))
        )
        burners = b_res.scalars().all()
    else:
        burners = []
    wallets = await _fetch(CryptoWallet)
    alerts = await _fetch(Alert)
    media = await _fetch(MediaAsset)

    # Phone identifiers confirmed by WhatsApp/Telegram get a special flag
    phone_idents = [i for i in idents if i.type == "phone"]
    for pi in phone_idents:
        meta = pi.meta or {}
        {
            "whatsapp_confirmed": meta.get("confirmed_whatsapp", False),
            "telegram_confirmed": meta.get("confirmed_telegram", False),
        }

    return {
        "person": _model_to_dict(p),
        "aliases": [_model_to_dict(a) for a in aliases],
        "identifiers": [
            {
                **_model_to_dict(i),
                "whatsapp_confirmed": (i.meta or {}).get("confirmed_whatsapp", False),
                "telegram_confirmed": (i.meta or {}).get("confirmed_telegram", False),
            }
            for i in idents
        ],
        "social_profiles": [_model_to_dict(s) for s in profiles],
        "addresses": [_model_to_dict(a) for a in addresses],
        "employment": [_model_to_dict(e) for e in employment],
        "darkweb_mentions": [_model_to_dict(d) for d in darkweb],
        "watchlist_matches": [_model_to_dict(w) for w in watchlist],
        "breach_records": [_model_to_dict(b) for b in breaches],
        "criminal_records": [_model_to_dict(r) for r in criminal],
        "identity_documents": [_model_to_dict(d) for d in documents],
        "credit_profiles": [_model_to_dict(c) for c in credit],
        "identifier_history": [_model_to_dict(h) for h in history],
        "behavioural_profiles": [_model_to_dict(b) for b in behavioural],
        "burner_assessments": [_model_to_dict(b) for b in burners],
        "crypto_wallets": [_model_to_dict(w) for w in wallets],
        "alerts": [_model_to_dict(a) for a in alerts],
        "media_assets": [_model_to_dict(m) for m in media],
        "summary": {
            "identifier_count": len(idents),
            "phone_count": len(phone_idents),
            "alias_count": len(aliases),
            "platform_count": len(profiles),
            "address_count": len(addresses),
            "employment_count": len(employment),
            "darkweb_hits": len(darkweb),
            "watchlist_hits": len(watchlist),
            "breach_count": len(breaches),
            "criminal_count": len(criminal),
            "document_count": len(documents),
            "has_criminal_record": len(criminal) > 0,
            "has_sex_offender": any(r.is_sex_offender for r in criminal),
            "has_bankruptcy": any(c.has_bankruptcy for c in credit),
            "has_sanctions": len(watchlist) > 0,
            "has_darkweb": len(darkweb) > 0,
            "crypto_wallet_count": len(wallets),
            "alert_count": len(alerts),
            "identifier_history_count": len(history),
        },
    }


@router.patch("/{person_id}")
async def update_person(person_id: str, updates: dict, session: AsyncSession = DbDep):
    uid = _parse_uuid(person_id)
    p = await _require_person(session, uid)

    ALLOWED = {
        "full_name",
        "gender",
        "nationality",
        "primary_language",
        "bio",
        "profile_image_url",
        "meta",
    }
    for field, value in updates.items():
        if field in ALLOWED:
            setattr(p, field, value)

    await session.commit()
    return {"message": "Person updated", "person_id": person_id}


@router.delete("/{person_id}")
async def delete_person(person_id: str, session: AsyncSession = DbDep):
    from datetime import datetime

    uid = _parse_uuid(person_id)
    p = await _require_person(session, uid)

    if hasattr(p, "deleted_at"):
        p.deleted_at = datetime.now(UTC)
        await session.commit()
        return {"message": "Person soft-deleted", "person_id": person_id}
    else:
        await session.delete(p)
        await session.commit()
        return {"message": "Person deleted", "person_id": person_id}


# ── Deduplication ──────────────────────────────────────────────────────────────


@router.post("/deduplicate")
async def scan_duplicates(
    limit: int = Query(200, le=1000, description="Max persons to scan"),
    threshold: float = Query(0.75, ge=0.0, le=1.0, description="Similarity threshold"),
    session: AsyncSession = DbDep,
):
    """
    Scan the persons table for likely duplicates.
    Returns merge candidates sorted by similarity score descending.
    """
    from modules.enrichers.deduplication import find_duplicate_persons

    persons = (await session.execute(select(Person).limit(limit))).scalars().all()

    idents_all = (
        (
            await session.execute(
                select(Identifier).where(Identifier.person_id.in_([p.id for p in persons]))
            )
        )
        .scalars()
        .all()
    )

    idents_by_person: dict = {}
    for i in idents_all:
        idents_by_person.setdefault(str(i.person_id), []).append(i.normalized_value or i.value)

    person_dicts = [
        {
            "id": str(p.id),
            "full_name": p.full_name or "",
            "dob": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "identifiers": idents_by_person.get(str(p.id), []),
        }
        for p in persons
    ]

    candidates = find_duplicate_persons(person_dicts)

    # Filter by requested threshold
    candidates = [c for c in candidates if c.similarity_score >= threshold]
    candidates.sort(key=lambda c: c.similarity_score, reverse=True)

    # Enrich candidates with person names for UI
    person_name_map = {str(p.id): p.full_name for p in persons}

    return {
        "candidates": [
            {
                "id_a": c.id_a,
                "name_a": person_name_map.get(c.id_a),
                "id_b": c.id_b,
                "name_b": person_name_map.get(c.id_b),
                "similarity_score": round(c.similarity_score, 3),
                "match_reasons": c.match_reasons,
            }
            for c in candidates
        ],
        "total_scanned": len(persons),
        "candidates_found": len(candidates),
    }


class MergeRequest(BaseModel):
    canonical_id: str
    duplicate_id: str


@router.post("/merge")
async def merge_persons(req: MergeRequest, session: AsyncSession = DbDep):
    """
    Merge duplicate_id into canonical_id.
    Reassigns all related rows then deletes the duplicate person record.
    """
    can_uid = _parse_uuid(req.canonical_id)
    dup_uid = _parse_uuid(req.duplicate_id)

    if can_uid == dup_uid:
        raise HTTPException(400, "canonical_id and duplicate_id must be different")

    canonical = await _require_person(session, can_uid)
    duplicate = await _require_person(session, dup_uid)

    from shared.models.alert import Alert
    from shared.models.behavioural import BehaviouralProfile
    from shared.models.breach import BreachRecord
    from shared.models.crawl import CrawlJob
    from shared.models.darkweb import DarkwebMention
    from shared.models.employment import EmploymentHistory
    from shared.models.watchlist import WatchlistMatch

    # All models with person_id FK — reassign them all to the canonical person
    reassign_models = [
        Identifier,
        SocialProfile,
        Alias,
        Address,
        EmploymentHistory,
        DarkwebMention,
        WatchlistMatch,
        BreachRecord,
        BehaviouralProfile,
        CrawlJob,
        Alert,
        CriminalRecord,
        IdentityDocument,
        CreditProfile,
        IdentifierHistory,
    ]

    for model in reassign_models:
        try:
            await session.execute(
                update(model).where(model.person_id == dup_uid).values(person_id=can_uid)
            )
        except Exception:
            # Model may not have person_id — skip
            pass

    # Merge quality scores (take better values)
    canonical.corroboration_count += duplicate.corroboration_count
    canonical.source_reliability = max(canonical.source_reliability, duplicate.source_reliability)
    canonical.composite_quality = max(canonical.composite_quality, duplicate.composite_quality)
    if duplicate.default_risk_score > canonical.default_risk_score:
        canonical.default_risk_score = duplicate.default_risk_score

    # Delete the duplicate
    await session.execute(delete(Person).where(Person.id == dup_uid))
    await session.commit()

    # Re-index the canonical person
    try:
        from shared.events import event_bus

        await event_bus.enqueue({"person_id": str(can_uid)}, priority="index")
    except Exception:
        pass

    return {
        "message": "Merge complete",
        "canonical_id": str(can_uid),
        "duplicate_id": str(dup_uid),
        "corroboration_count": canonical.corroboration_count,
    }


# ── Region-scoped re-enrichment ────────────────────────────────────────────────


class RegionGrowRequest(BaseModel):
    city: str | None = None
    state: str | None = None
    country: str | None = None
    limit: int = 20  # number of surnames to sweep (each hits 3 platforms = ~60 jobs)
    priority: str = "normal"


@router.post("/region/grow")
async def grow_region(req: RegionGrowRequest, session: AsyncSession = DbDep):
    """
    Discover new people in a geographic region by querying location-aware crawlers.

    Seeds common surname + location queries against whitepages, fastpeoplesearch,
    and truepeoplesearch to find real people in that area. Each discovered person
    is added to the DB and fully enriched.
    """
    from modules.crawlers.registry import CRAWLER_REGISTRY
    from modules.dispatcher.dispatcher import dispatch_job
    from shared.constants import CrawlStatus
    from shared.models.crawl import CrawlJob

    if not any([req.city, req.state, req.country]):
        raise HTTPException(400, "At least one of city, state, country is required")

    # Build location string for crawlers that accept "Name|City,State" format
    location_parts = []
    if req.city:
        location_parts.append(req.city)
    if req.state:
        location_parts.append(req.state)
    location_str = ",".join(location_parts) if location_parts else (req.country or "")

    # Common surnames to seed discovery — produces a broad sweep
    SEED_SURNAMES = [
        "Smith",
        "Johnson",
        "Williams",
        "Brown",
        "Jones",
        "Miller",
        "Davis",
        "Wilson",
        "Taylor",
        "Anderson",
        "Thomas",
        "Jackson",
        "White",
        "Harris",
        "Martin",
        "Thompson",
        "Garcia",
        "Martinez",
        "Robinson",
        "Clark",
    ]

    # Location-aware people-search crawlers
    LOCATION_PLATFORMS = [
        p for p in ("whitepages", "fastpeoplesearch", "truepeoplesearch") if p in CRAWLER_REGISTRY
    ]

    queued_searches: list[str] = []

    for surname in SEED_SURNAMES[: req.limit]:
        identifier = f"{surname}|{location_str}" if location_str else surname

        # No placeholder Person — let the aggregator create real persons
        # from actual crawler results. CrawlJob.person_id is nullable.
        for platform in LOCATION_PLATFORMS:
            job = CrawlJob(
                id=uuid.uuid4(),
                person_id=None,
                status=CrawlStatus.PENDING.value,
                job_type="crawl",
                seed_identifier=identifier,
                meta={"platform": platform, "region_grow": True, "location": location_str},
            )
            session.add(job)
            await session.flush()
            await dispatch_job(
                platform=platform,
                identifier=identifier,
                person_id=None,
                priority=req.priority,
                job_id=str(job.id),
            )
            queued_searches.append(f"{platform}:{identifier}")

    await session.commit()

    return {
        "message": f"Region grow launched — discovering people in {location_str}",
        "seed_searches": len(SEED_SURNAMES[: req.limit]),
        "platforms_used": LOCATION_PLATFORMS,
        "jobs_queued": len(queued_searches),
        "region": {"city": req.city, "state": req.state, "country": req.country},
        "note": "Real persons will appear in /persons only when crawlers return confirmed data.",
    }


# ── Criminal records ───────────────────────────────────────────────────────────


@router.get("/{person_id}/criminal")
async def get_criminal_records(person_id: str, session: AsyncSession = DbDep):
    """All criminal records for a person — arrests, charges, convictions, warrants."""
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)
    records = (
        (
            await session.execute(
                select(CriminalRecord)
                .where(CriminalRecord.person_id == uid)
                .order_by(CriminalRecord.arrest_date.desc().nullslast())
            )
        )
        .scalars()
        .all()
    )
    return {
        "person_id": person_id,
        "criminal_records": [_model_to_dict(r) for r in records],
        "total": len(records),
        "has_sex_offender": any(r.is_sex_offender for r in records),
        "felony_count": sum(1 for r in records if r.offense_level == "felony"),
        "misdemeanor_count": sum(1 for r in records if r.offense_level == "misdemeanor"),
    }


# ── Identity documents ─────────────────────────────────────────────────────────


@router.get("/{person_id}/documents")
async def get_identity_documents(person_id: str, session: AsyncSession = DbDep):
    """Identity documents (driver's license, passport, SSN partial, etc.)."""
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)
    docs = (
        (
            await session.execute(
                select(IdentityDocument)
                .where(IdentityDocument.person_id == uid)
                .order_by(IdentityDocument.is_active.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "person_id": person_id,
        "documents": [_model_to_dict(d) for d in docs],
        "total": len(docs),
    }


# ── Credit profile ─────────────────────────────────────────────────────────────


@router.get("/{person_id}/credit")
async def get_credit_profile(person_id: str, session: AsyncSession = DbDep):
    """Credit/financial profile — public record signals, inferred credit tier."""
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)
    profiles = (
        (
            await session.execute(
                select(CreditProfile)
                .where(CreditProfile.person_id == uid)
                .order_by(CreditProfile.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "person_id": person_id,
        "credit_profiles": [_model_to_dict(cp) for cp in profiles],
        "total": len(profiles),
        "has_bankruptcy": any(cp.has_bankruptcy for cp in profiles),
        "has_tax_lien": any(cp.has_tax_lien for cp in profiles),
        "has_foreclosure": any(cp.has_foreclosure for cp in profiles),
    }


# ── Identifier history ─────────────────────────────────────────────────────────


@router.get("/{person_id}/history")
async def get_identifier_history(
    person_id: str,
    id_type: str | None = Query(None, description="Filter by type: phone, email, handle"),
    session: AsyncSession = DbDep,
):
    """All historical phones, emails, handles observed for this person."""
    uid = _parse_uuid(person_id)
    await _require_person(session, uid)

    q = select(IdentifierHistory).where(IdentifierHistory.person_id == uid)
    if id_type:
        q = q.where(IdentifierHistory.type == id_type)
    q = q.order_by(IdentifierHistory.last_seen_at.desc())

    history = (await session.execute(q)).scalars().all()
    return {
        "person_id": person_id,
        "history": [_model_to_dict(h) for h in history],
        "total": len(history),
        "phones": [h.value for h in history if h.type == "phone"],
        "emails": [h.value for h in history if h.type == "email"],
        "handles": [h.value for h in history if h.type == "handle"],
    }


# ── Internal helpers ───────────────────────────────────────────────────────────


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {value!r}")


async def _require_person(session: AsyncSession, uid: uuid.UUID) -> Person:
    p = await session.get(Person, uid)
    if not p:
        raise HTTPException(404, "Person not found")
    return p
