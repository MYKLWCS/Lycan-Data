"""
Persons API — CRUD, reporting, deduplication, and merge endpoints.
"""

import logging
import uuid


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards in user input."""
    return value.replace("%", r"\%").replace("_", r"\_")


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
logger = logging.getLogger(__name__)

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
        "enrichment_score": p.enrichment_score,
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
        base_q = base_q.where(Person.full_name.ilike(f"%{_escape_like(q)}%"))

    # Region filter — join to addresses
    if city or state or country:
        addr_sub = select(Address.person_id).distinct()
        if city:
            addr_sub = addr_sub.where(Address.city.ilike(f"%{_escape_like(city)}%"))
        if state:
            addr_sub = addr_sub.where(Address.state_province.ilike(f"%{_escape_like(state)}%"))
        if country:
            addr_sub = addr_sub.where(Address.country.ilike(f"%{_escape_like(country)}%"))
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
        "enrichment_score": p.enrichment_score,
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
    from shared.models.education import Education
    from shared.models.employment import EmploymentHistory
    from shared.models.intelligence import EmailIntelligence, PhoneIntelligence
    from shared.models.media import MediaAsset
    from shared.models.professional import CorporateDirectorship, ProfessionalLicense
    from shared.models.property import Property
    from shared.models.vehicle import Aircraft, Vehicle, Vessel
    from shared.models.watchlist import WatchlistMatch
    from shared.models.wealth import WealthAssessment

    async def _fetch(model, order_by=None):
        q = select(model).where(model.person_id == uid)
        if order_by is not None:  # pragma: no cover
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
    education = await _fetch(Education)
    properties = await _fetch(Property)
    vehicles = await _fetch(Vehicle)
    aircraft = await _fetch(Aircraft)
    vessels = await _fetch(Vessel)
    licenses = await _fetch(ProfessionalLicense)
    directorships = await _fetch(CorporateDirectorship)
    phone_intel = await _fetch(PhoneIntelligence)
    email_intel = await _fetch(EmailIntelligence)
    wealth = await _fetch(WealthAssessment)
    alerts = await _fetch(Alert)
    media = await _fetch(MediaAsset)

    # Commercial tags (Phase 4 MarketingTag rows for this person)
    from shared.models.marketing import MarketingTag

    tags_rows = await _fetch(MarketingTag)

    # Connections — person relationships
    from shared.models.relationship import Relationship

    rels_res = await session.execute(select(Relationship).where(Relationship.person_a_id == uid))
    rels = rels_res.scalars().all()

    related_ids = [r.person_b_id for r in rels]
    related_persons: dict = {}
    if related_ids:
        rp_res = await session.execute(select(Person).where(Person.id.in_(related_ids)))
        for rp in rp_res.scalars().all():
            related_persons[rp.id] = rp

    # Coverage — crawl history for this person
    from shared.models.crawl import CrawlJob, DataSource

    crawl_jobs_res = await session.execute(
        select(CrawlJob)
        .where(CrawlJob.person_id == uid)
        .order_by(CrawlJob.completed_at.desc().nullslast())
    )
    crawl_jobs = crawl_jobs_res.scalars().all()

    sources_enabled_count = int(
        (
            await session.execute(
                select(func.count()).select_from(DataSource).where(DataSource.is_enabled.is_(True))
            )
        ).scalar_one()
        or 0
    )

    sources_attempted = len({(j.meta or {}).get("platform", str(j.id)) for j in crawl_jobs})
    sources_found = sum(
        1
        for j in crawl_jobs
        if (j.status or "") in ("done", "complete", "success", "found")
        or int(j.result_count or 0) > 0
    )
    coverage_pct = (
        round(sources_found / sources_enabled_count * 100) if sources_enabled_count > 0 else 0
    )

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
        "education_history": [_model_to_dict(e) for e in education],
        "properties": [_model_to_dict(p) for p in properties],
        "vehicles": [_model_to_dict(v) for v in vehicles],
        "aircraft": [_model_to_dict(a) for a in aircraft],
        "vessels": [_model_to_dict(v) for v in vessels],
        "professional_licenses": [_model_to_dict(l) for l in licenses],
        "corporate_directorships": [_model_to_dict(d) for d in directorships],
        "phone_intelligence": [_model_to_dict(p) for p in phone_intel],
        "email_intelligence": [_model_to_dict(e) for e in email_intel],
        "wealth_assessments": [_model_to_dict(w) for w in wealth],
        "alerts": [_model_to_dict(a) for a in alerts],
        "media_assets": [_model_to_dict(m) for m in media],
        "commercial_tags": [
            {
                "tag": t.tag,
                "category": t.tag_category,
                "confidence": t.confidence,
                "reasoning": t.reasoning if isinstance(t.reasoning, list) else [],
                "scored_at": t.scored_at.isoformat() if t.scored_at else None,
            }
            for t in tags_rows
        ],
        "connections": {
            "persons": [
                {
                    "person_id": str(r.person_b_id),
                    "full_name": (
                        related_persons[r.person_b_id].full_name
                        if r.person_b_id in related_persons
                        else None
                    ),
                    "relationship_type": r.rel_type,
                    "relationship_score": r.score,
                    "shared_identifier_count": (r.evidence or {}).get("shared_identifier_count", 0),
                }
                for r in rels
            ],
            "entities": [],
        },
        "coverage": {
            "sources_enabled": sources_enabled_count,
            "sources_attempted": sources_attempted,
            "sources_found": sources_found,
            "coverage_pct": coverage_pct,
            "crawl_history": [
                {
                    "crawler": (j.meta or {}).get("platform", "unknown"),
                    "ran_at": j.completed_at.isoformat() if j.completed_at else None,
                    "status": j.status,
                    "source_reliability": None,
                }
                for j in crawl_jobs
            ],
        },
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
            "education_count": len(education),
            "property_count": len(properties),
            "vehicle_count": len(vehicles),
            "aircraft_count": len(aircraft),
            "vessel_count": len(vessels),
            "license_count": len(licenses),
            "directorship_count": len(directorships),
            "phone_intel_count": len(phone_intel),
            "email_intel_count": len(email_intel),
            "wealth_assessment_count": len(wealth),
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


@router.post("/{person_id}/flag")
async def flag_person_for_review(person_id: str, session: AsyncSession = DbDep):
    """Set conflict_flag=True on a person to queue for manual review."""
    uid = _parse_uuid(person_id)
    p = await _require_person(session, uid)
    p.conflict_flag = True
    await session.commit()
    return {"message": "Flagged for review", "person_id": person_id}


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
            logger.debug(
                "Skipping reassignment for model %s without compatible person_id column",
                model.__name__,
                exc_info=True,
            )

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
        logger.debug("Re-index enqueue failed after person merge for %s", can_uid, exc_info=True)

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


# ── Family tree ────────────────────────────────────────────────────────────────


@router.get("/{person_id}/family-tree")
async def get_family_tree(
    person_id: str,
    depth_ancestors: int = Query(4, ge=1, le=8),
    depth_descendants: int = Query(3, ge=1, le=5),
    session: AsyncSession = DbDep,
):
    """Return FamilyTreeSnapshot or trigger build if none exists."""
    from sqlalchemy import desc

    from shared.models.family_tree import FamilyTreeSnapshot

    uid = _parse_uuid(person_id)
    result = await session.execute(
        select(FamilyTreeSnapshot)
        .where(
            FamilyTreeSnapshot.root_person_id == uid,
            FamilyTreeSnapshot.is_stale.is_(False),
        )
        .order_by(desc(FamilyTreeSnapshot.built_at))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    tree = snapshot.tree_json if snapshot else None

    # Fallback: build tree from relationships if no snapshot at all
    if tree is None:
        from shared.models.relationship import Relationship

        person = await session.get(Person, uid)
        if not person:
            return {
                "status": "not_built",
                "message": "POST /persons/{id}/family-tree/build to start",
                "tree_json": {"nodes": {}, "edges": []},
                "members": [],
            }

        rels = (
            (
                await session.execute(
                    select(Relationship).where(
                        (Relationship.person_a_id == uid) | (Relationship.person_b_id == uid)
                    )
                )
            )
            .scalars()
            .all()
        )

        # Inverse relationship mapping for correct generation direction
        _INVERSE_REL = {
            "parent_of": "child_of",
            "child_of": "parent_of",
            "grandparent_of": "grandchild_of",
            "grandchild_of": "grandparent_of",
            "spouse_of": "spouse_of",
            "sibling_of": "sibling_of",
            "associate": "associate",
            "co-location": "co-location",
            "shared_identifier": "shared_identifier",
        }
        # Generation delta: positive = older generation, negative = younger
        _GEN_DELTA = {
            "parent_of": -1,
            "child_of": 1,
            "grandparent_of": -2,
            "grandchild_of": 2,
            "spouse_of": 0,
            "sibling_of": 0,
        }

        nodes = {str(uid): {"person_id": str(uid), "full_name": person.full_name, "generation": 0}}
        edges = []

        # BFS to compute generations
        from collections import deque

        visited = {uid}
        queue = deque([(uid, 0)])

        while queue:
            current_id, current_gen = queue.popleft()
            for r in rels:
                if r.person_a_id == current_id:
                    other_id = r.person_b_id
                    rel_type = r.relationship_type or "associate"
                elif r.person_b_id == current_id:
                    other_id = r.person_a_id
                    rel_type = _INVERSE_REL.get(
                        r.relationship_type or "", r.relationship_type or "associate"
                    )
                else:
                    continue

                if other_id in visited:
                    continue
                visited.add(other_id)

                gen_delta = _GEN_DELTA.get(rel_type, 0)
                other_gen = current_gen + gen_delta

                other = await session.get(Person, other_id)
                nodes[str(other_id)] = {
                    "person_id": str(other_id),
                    "full_name": other.full_name if other else "Unknown",
                    "generation": other_gen,
                    "date_of_birth": str(other.date_of_birth)
                    if other and other.date_of_birth
                    else None,
                }

                edges.append(
                    {
                        "source": str(r.person_a_id),
                        "target": str(r.person_b_id),
                        "person_a_id": str(r.person_a_id),
                        "person_b_id": str(r.person_b_id),
                        "relationship_type": r.relationship_type,
                        "confidence": r.confidence_score,
                    }
                )

                queue.append((other_id, other_gen))

        tree = {"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)}

    if not tree or (not tree.get("nodes") and not snapshot):
        return {
            "status": "not_built",
            "message": "POST /persons/{id}/family-tree/build to start",
        }

    # Normalize nodes: enricher stores list of UUIDs, fallback stores keyed dict
    raw_nodes = tree.get("nodes") or {}
    if isinstance(raw_nodes, list):
        # Convert UUID list to keyed dict with person details
        node_dict = {}
        for node_id in raw_nodes:
            pid = node_id if isinstance(node_id, str) else str(node_id)
            try:
                p = await session.get(Person, uuid.UUID(pid))
                node_dict[pid] = {
                    "person_id": pid,
                    "full_name": p.full_name if p else "Unknown",
                    "date_of_birth": str(p.date_of_birth) if p and p.date_of_birth else None,
                }
            except Exception:
                node_dict[pid] = {"person_id": pid, "full_name": "Unknown"}
        tree["nodes"] = node_dict
        raw_nodes = node_dict

    members = []
    if isinstance(raw_nodes, dict):
        members = [
            {"person_id": v.get("person_id", k), "full_name": v.get("full_name", "Unknown")}
            for k, v in raw_nodes.items()
        ]

    return {
        "root_person_id": str(snapshot.root_person_id) if snapshot else str(uid),
        "tree_json": tree,
        "depth_ancestors": snapshot.depth_ancestors if snapshot else depth_ancestors,
        "depth_descendants": snapshot.depth_descendants if snapshot else depth_descendants,
        "source_count": snapshot.source_count if snapshot else len(tree.get("edges", [])),
        "built_at": snapshot.built_at.isoformat() if snapshot and snapshot.built_at else None,
        "is_stale": snapshot.is_stale if snapshot else False,
        "members": members,
    }


@router.post("/{person_id}/link-identifier")
async def link_identifier(
    person_id: str,
    identifier_type: str = Query(..., description="phone, email, username, etc."),
    value: str = Query(..., description="The identifier value"),
    session: AsyncSession = DbDep,
):
    """Manually link an identifier to a person. Also merges if the identifier exists on another person."""
    uid = _parse_uuid(person_id)
    person = await session.get(Person, uid)
    if not person:
        raise HTTPException(404, "Person not found")

    from shared.utils import normalize_identifier

    norm = normalize_identifier(value, identifier_type)

    # Check if this identifier already exists on another person
    existing = (
        await session.execute(
            select(Identifier)
            .where(
                Identifier.normalized_value == norm,
                Identifier.type == identifier_type,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing and existing.person_id and existing.person_id != uid:
        # Move identifier directly (merge executor has session issues)
        other_pid = existing.person_id
        existing.person_id = uid
        # Move ALL identifiers from the other person
        from sqlalchemy import update

        await session.execute(
            update(Identifier).where(Identifier.person_id == other_pid).values(person_id=uid)
        )
        # Mark other person as merged
        other_person = await session.get(Person, other_pid)
        if other_person:
            other_person.merged_into = uid
        await session.commit()
        return {"linked": True, "merged_person": str(other_pid), "identifier": norm}

    if existing and existing.person_id == uid:
        return {"linked": True, "already_exists": True, "identifier": norm}

    # Create new identifier
    new_ident = Identifier(
        id=uuid.uuid4(),
        person_id=uid,
        type=identifier_type,
        value=value,
        normalized_value=norm,
        confidence=1.0,
        is_primary=False,
        meta={"source": "manual_link"},
    )
    session.add(new_ident)
    await session.commit()
    return {"linked": True, "identifier": norm, "type": identifier_type}


@router.post("/{person_id}/family-tree/build")
async def build_family_tree(person_id: str, session: AsyncSession = DbDep):
    """Trigger full family tree rebuild."""
    uid = _parse_uuid(person_id)
    person = await session.get(Person, uid)
    if not person:
        raise HTTPException(404, "Person not found")
    person.meta = person.meta or {}
    person.meta["needs_genealogy"] = "true"
    await session.commit()
    return {"status": "queued", "person_id": person_id}


@router.get("/{person_id}/family-tree/status")
async def family_tree_status(person_id: str, session: AsyncSession = DbDep):
    """Return build progress."""
    from sqlalchemy import desc

    from shared.models.family_tree import FamilyTreeSnapshot

    uid = _parse_uuid(person_id)
    result = await session.execute(
        select(FamilyTreeSnapshot)
        .where(FamilyTreeSnapshot.root_person_id == uid)
        .order_by(desc(FamilyTreeSnapshot.built_at))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        return {"status": "not_started"}
    return {
        "status": "complete" if not snapshot.is_stale else "stale",
        "built_at": snapshot.built_at.isoformat() if snapshot.built_at else None,
        "source_count": snapshot.source_count,
    }


@router.get("/{person_id}/family-tree/gedcom")
async def get_family_tree_gedcom(person_id: str, session: AsyncSession = DbDep):
    """Export the family tree as a GEDCOM 5.5.5 file."""
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import desc

    from modules.export.gedcom import export_gedcom
    from shared.models.family_tree import FamilyTreeSnapshot
    from shared.models.relationship import Relationship

    uid = _parse_uuid(person_id)
    await _require_person(session, uid)

    result = await session.execute(
        select(FamilyTreeSnapshot)
        .where(FamilyTreeSnapshot.root_person_id == uid)
        .order_by(desc(FamilyTreeSnapshot.built_at))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(404, "No family tree built yet — POST /build first")

    node_ids = snapshot.tree_json.get("nodes", [])
    persons_out: list[dict] = []
    for nid in node_ids:
        try:
            p = await session.get(Person, uuid.UUID(nid))
            if p:
                persons_out.append(
                    {
                        "full_name": p.full_name,
                        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
                        "gender": p.gender,
                    }
                )
        except Exception:
            logger.debug("Failed to serialize relationship-linked rows for %s", uid, exc_info=True)

    from sqlalchemy import or_

    rels_result = await session.execute(
        select(Relationship).where(
            or_(Relationship.person_a_id == uid, Relationship.person_b_id == uid)
        )
    )
    rels = [
        {
            "person_a_id": str(r.person_a_id),
            "person_b_id": str(r.person_b_id),
            "rel_type": r.rel_type,
        }
        for r in rels_result.scalars().all()
    ]

    gedcom_content = export_gedcom(persons_out, rels)
    return PlainTextResponse(
        content=gedcom_content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="family_tree_{person_id[:8]}.ged"'},
    )


@router.get("/{person_id}/relatives")
async def list_relatives(
    person_id: str,
    session: AsyncSession = DbDep,
):
    """Flat list of all known relatives."""
    from shared.models.relationship import Relationship

    uid = _parse_uuid(person_id)
    from sqlalchemy import or_

    result = await session.execute(
        select(Relationship).where(
            or_(Relationship.person_a_id == uid, Relationship.person_b_id == uid)
        )
    )
    rels = result.scalars().all()
    relatives = []
    for r in rels:
        # Determine who the "other" person is in this relationship
        other_id = r.person_b_id if r.person_a_id == uid else r.person_a_id
        other = await session.get(Person, other_id)
        relatives.append(
            {
                "person_id": str(other_id),
                "full_name": other.full_name if other else None,
                "relationship_type": r.rel_type,
                "confidence": r.score,
            }
        )
    return {"person_id": person_id, "relatives": relatives, "count": len(relatives)}


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
