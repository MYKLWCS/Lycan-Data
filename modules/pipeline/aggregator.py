"""
Person Aggregation Pipeline.

Takes a CrawlerResult and writes it into the correct DB tables,
linked to the right Person. Handles all result types.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from modules.crawlers.result import CrawlerResult
from shared.constants import (
    IdentifierType, Platform, AlertType, AlertSeverity,
)
from shared.data_quality import apply_quality_to_model, assess_quality
from shared.models.person import Person
from shared.models.identifier import Identifier
from shared.models.social_profile import SocialProfile
from shared.models.address import Address
from shared.models.behavioural import BehaviouralProfile
from shared.models.burner import BurnerAssessment
from shared.models.watchlist import WatchlistMatch
from shared.models.darkweb import DarkwebMention
from shared.models.alert import Alert
from shared.models.breach import BreachRecord

logger = logging.getLogger(__name__)

# Platforms that represent a social media profile
_SOCIAL_PLATFORMS = {p.value for p in Platform}

# Phone enrichment platform keys
_PHONE_PLATFORMS = {"phone_carrier", "phone_fonefinder", "phone_truecaller"}

# Email breach platform keys
_EMAIL_BREACH_PLATFORMS = {
    "email_hibp", "email_holehe", "email_leakcheck", "email_breach",
}

# Sanctions / watchlist platform keys
_SANCTIONS_PLATFORMS = {"sanctions_ofac", "sanctions_un", "sanctions_fbi"}

# Dark-web / paste platform keys
_DARKWEB_PLATFORMS = {
    "darkweb_ahmia", "darkweb_torch",
    "paste_pastebin", "paste_ghostbin", "paste_psbdmp",
    "telegram_dark",
}

# People-search platform keys
_PEOPLE_SEARCH_PLATFORMS = {
    "whitepages", "fastpeoplesearch", "truepeoplesearch",
}

# Court record platform keys
_COURT_PLATFORMS = {"court_courtlistener", "court_state"}


async def aggregate_result(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: str | None = None,
) -> dict[str, Any]:
    """
    Main entry point. Routes result to the correct sub-handlers based on platform.

    Returns a summary dict describing what was written. Commits the session on
    success so the caller doesn't have to.
    """
    if not result.found or not result.data:
        return {"written": False, "reason": "no data"}

    written: dict[str, Any] = {}

    person = await _get_or_create_person(session, person_id, result)
    written["person_id"] = str(person.id)

    platform = (result.platform or "").lower()

    # Social profile ─────────────────────────────────────────────────────────
    if platform in _SOCIAL_PLATFORMS:
        profile = await _upsert_social_profile(session, result, person.id)
        written["social_profile"] = str(profile.id) if profile else None

    # Phone enrichment ────────────────────────────────────────────────────────
    if platform in _PHONE_PLATFORMS:
        await _handle_phone_enrichment(session, result, person.id)
        written["phone_enrichment"] = True

    # Email breach data ───────────────────────────────────────────────────────
    if platform in _EMAIL_BREACH_PLATFORMS:
        count = await _handle_breach_data(session, result, person.id)
        written["breach_data"] = True
        written["breach_count"] = count

    # Sanctions / watchlist hits ──────────────────────────────────────────────
    if platform in _SANCTIONS_PLATFORMS:
        hits = await _handle_watchlist(session, result, person.id)
        written["watchlist_hits"] = hits

    # Dark-web / paste mentions ───────────────────────────────────────────────
    if platform in _DARKWEB_PLATFORMS:
        await _handle_darkweb(session, result, person.id)
        written["darkweb"] = True

    # People-search addresses ─────────────────────────────────────────────────
    if platform in _PEOPLE_SEARCH_PLATFORMS:
        await _handle_people_search(session, result, person.id)
        written["addresses"] = True

    # Court / legal records ───────────────────────────────────────────────────
    if platform in _COURT_PLATFORMS:
        await _handle_court_records(session, result, person.id)
        written["court_records"] = True

    # Behavioural signals ─────────────────────────────────────────────────────
    if platform == "social_posts_analyzer":
        await _handle_behavioural(session, result, person.id)
        written["behavioural"] = True

    await session.commit()
    return written


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_or_create_person(
    session: AsyncSession,
    person_id: str | None,
    result: CrawlerResult,
) -> Person:
    """Return an existing Person or create a new one."""
    if person_id:
        p = await session.get(Person, uuid.UUID(person_id))
        if p:
            return p

    # Try to find by full_name if result carries one
    full_name = (
        result.data.get("name")
        or result.data.get("full_name")
        or result.data.get("display_name")
    )
    if full_name:
        existing = (await session.execute(
            select(Person).where(Person.full_name == full_name).limit(1)
        )).scalar_one_or_none()
        if existing:
            return existing

    p = Person(id=uuid.uuid4(), full_name=full_name)
    session.add(p)
    await session.flush()
    return p


async def _upsert_social_profile(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> SocialProfile | None:
    """Insert or update a SocialProfile row from a CrawlerResult."""
    data = result.data or {}
    handle = (
        data.get("handle")
        or data.get("username")
        or data.get("display_name")
        or result.identifier
    )

    existing = (await session.execute(
        select(SocialProfile).where(
            SocialProfile.platform == result.platform,
            SocialProfile.handle == handle,
        ).limit(1)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if existing:
        # Update mutable fields — never overwrite with None
        existing.follower_count = data.get("follower_count") or existing.follower_count
        existing.following_count = data.get("following_count") or existing.following_count
        existing.post_count = data.get("post_count") or existing.post_count
        existing.bio = data.get("bio") or existing.bio
        existing.display_name = data.get("display_name") or existing.display_name
        existing.is_verified = data.get("is_verified", False) or existing.is_verified
        existing.is_private = data.get("is_private", False) or existing.is_private
        existing.last_scraped_at = now
        existing.person_id = person_id
        apply_quality_to_model(
            existing,
            last_scraped_at=now,
            source_type="social_media_profile",
            source_name=result.platform,
            corroboration_count=1,
        )
        return existing

    profile = SocialProfile(
        id=uuid.uuid4(),
        person_id=person_id,
        platform=result.platform,
        handle=handle,
        url=result.profile_url,
        display_name=data.get("display_name"),
        follower_count=data.get("follower_count"),
        following_count=data.get("following_count"),
        post_count=data.get("post_count"),
        bio=data.get("bio"),
        is_verified=data.get("is_verified", False),
        is_private=data.get("is_private", False),
        is_active=result.found,
        profile_data=data,
        last_scraped_at=now,
        scraped_from=result.profile_url or result.platform,
        source_reliability=result.source_reliability,
    )
    apply_quality_to_model(
        profile,
        last_scraped_at=now,
        source_type="social_media_profile",
        source_name=result.platform,
        corroboration_count=1,
    )
    session.add(profile)
    await session.flush()
    return profile


async def _handle_phone_enrichment(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist phone-carrier enrichment and compute a burner score."""
    from modules.enrichers.burner_detector import compute_burner_score, persist_burner_assessment

    data = result.data or {}

    # Find or create the phone Identifier
    ident = (await session.execute(
        select(Identifier).where(
            Identifier.person_id == person_id,
            Identifier.type == IdentifierType.PHONE.value,
            Identifier.value == result.identifier,
        ).limit(1)
    )).scalar_one_or_none()

    if not ident:
        ident = Identifier(
            id=uuid.uuid4(),
            person_id=person_id,
            type=IdentifierType.PHONE.value,
            value=result.identifier,
            normalized_value=result.identifier.strip(),
            confidence=0.9,
        )
        session.add(ident)
        await session.flush()

    carrier_name = data.get("carrier_name")
    line_type = data.get("line_type")
    area_code = result.identifier[2:5] if result.identifier.startswith("+1") else None

    score = compute_burner_score(
        phone=result.identifier,
        carrier_name=carrier_name,
        line_type=line_type,
        area_code=area_code,
    )
    await persist_burner_assessment(session, ident.id, score)


async def _handle_breach_data(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> int:
    """Write BreachRecord rows from HIBP-style or Holehe-style results."""
    data = result.data or {}
    count = 0

    # HIBP-style: list of breach dicts
    for breach in data.get("breaches") or []:
        raw_date = breach.get("date") or breach.get("breach_date")
        breach_date = None
        if raw_date:
            try:
                from datetime import date
                breach_date = date.fromisoformat(str(raw_date))
            except (ValueError, TypeError):
                breach_date = None

        br = BreachRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            breach_name=breach.get("name") or breach.get("domain") or "unknown",
            breach_date=breach_date,
            source_type="clearweb",
            exposed_fields=breach.get("data_classes") or [],
            raw_sample=str(breach),
            meta={"source_platform": result.platform},
        )
        session.add(br)
        count += 1

    # Holehe / registration-presence style: list of service names
    for service in data.get("found_on") or []:
        br = BreachRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            breach_name=str(service),
            source_type="clearweb",
            exposed_fields=["email_registration"],
            meta={"source_platform": "holehe"},
        )
        session.add(br)
        count += 1

    # LeakCheck / generic source list
    for item in data.get("sources") or []:
        br = BreachRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            breach_name=str(item.get("db") if isinstance(item, dict) else item),
            source_type="clearweb",
            exposed_fields=[],
            meta={"source_platform": result.platform},
        )
        session.add(br)
        count += 1

    return count


async def _handle_watchlist(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> int:
    """Write WatchlistMatch rows and raise CRITICAL alerts for each hit."""
    data = result.data or {}
    matches = data.get("matches") or []
    count = 0

    list_name = result.platform.replace("sanctions_", "").upper()

    for match in matches:
        wm = WatchlistMatch(
            id=uuid.uuid4(),
            person_id=person_id,
            list_name=list_name,
            list_type="sanctions",
            match_name=match.get("name", ""),
            match_score=float(match.get("score", 0.8)),
            reason=match.get("reason"),
            is_confirmed=False,
            meta={"raw": match, "source": result.platform},
        )
        session.add(wm)

        alert = Alert(
            id=uuid.uuid4(),
            person_id=person_id,
            alert_type=AlertType.SANCTIONS_HIT.value,
            severity=AlertSeverity.CRITICAL.value,
            title=f"Sanctions hit on {list_name}",
            body=f"Matched name: {match.get('name')} — score {match.get('score', 0.8):.2f}",
            payload={"match": match, "platform": result.platform},
        )
        session.add(alert)
        count += 1

    return count


async def _handle_darkweb(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Write DarkwebMention rows and HIGH alerts for dark-web hits."""
    data = result.data or {}
    mentions = data.get("mentions") or data.get("results") or []

    # Map platform to a source_type the model accepts
    platform = (result.platform or "").lower()
    if "paste" in platform:
        source_type = "paste_site"
    elif "market" in platform:
        source_type = "dark_market"
    elif "forum" in platform:
        source_type = "dark_forum"
    else:
        source_type = "dark_paste"

    for mention in mentions[:10]:
        url = mention.get("url") or mention.get("onion_url") or ""
        url_hash = hashlib.sha256(url.encode()).hexdigest() if url else None
        snippet = (
            mention.get("description")
            or mention.get("preview")
            or mention.get("content")
            or ""
        )[:500]

        dm = DarkwebMention(
            id=uuid.uuid4(),
            person_id=person_id,
            source_type=source_type,
            source_url_hashed=url_hash,
            mention_context=snippet or None,
            severity=AlertSeverity.HIGH.value,
            exposure_score=0.5,
            meta={
                "platform": result.platform,
                "title": mention.get("title", "")[:200],
                "url_preview": url[:100] if url else None,
            },
        )
        session.add(dm)

        title_preview = mention.get("title", "")[:80]
        alert = Alert(
            id=uuid.uuid4(),
            person_id=person_id,
            alert_type=AlertType.DARKWEB_MENTION.value,
            severity=AlertSeverity.HIGH.value,
            title=f"Dark web mention — {result.platform}",
            body=title_preview or f"Mention found on {result.platform}",
            payload={"platform": result.platform, "url_hash": url_hash},
        )
        session.add(alert)


async def _handle_people_search(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Write Address rows from people-search results (up to 3 per scrape)."""
    data = result.data or {}
    results = data.get("results") or []
    now = datetime.now(timezone.utc)

    for r in results[:3]:
        if not isinstance(r, dict):
            continue
        raw = str(r.get("address", "")).strip()
        if not raw:
            continue

        addr = Address(
            id=uuid.uuid4(),
            person_id=person_id,
            street=r.get("street"),
            city=r.get("city"),
            state_province=r.get("state"),
            country=r.get("country", "US"),
            country_code=r.get("country_code", "US"),
            meta={"raw_address": raw, "scraped_from": result.platform},
            last_scraped_at=now,
            scraped_from=result.platform,
            source_reliability=result.source_reliability,
        )
        apply_quality_to_model(
            addr,
            last_scraped_at=now,
            source_type="default",
            source_name=result.platform,
            corroboration_count=1,
        )
        session.add(addr)


async def _handle_court_records(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Raise a MEDIUM alert when court records are found."""
    data = result.data or {}
    cases = data.get("cases") or []
    if not cases:
        return

    alert = Alert(
        id=uuid.uuid4(),
        person_id=person_id,
        alert_type=AlertType.CRIMINAL_SIGNAL.value,
        severity=AlertSeverity.MEDIUM.value,
        title=f"Court records found via {result.platform}",
        body=f"{len(cases)} case(s) found.",
        payload={"case_count": len(cases), "platform": result.platform},
    )
    session.add(alert)


async def _handle_behavioural(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Update or create a BehaviouralProfile from social-post analysis signals."""
    data = result.data or {}

    gambling = 1.0 if data.get("gambling_language") else 0.0
    financial = 1.0 if data.get("financial_stress_language") else 0.0
    substance = 1.0 if data.get("substance_language") else 0.0
    aggression = 1.0 if data.get("aggression_language") else 0.0

    existing = (await session.execute(
        select(BehaviouralProfile).where(
            BehaviouralProfile.person_id == person_id
        ).limit(1)
    )).scalar_one_or_none()

    if existing:
        existing.gambling_score = max(existing.gambling_score or 0.0, gambling)
        existing.financial_distress_score = max(
            existing.financial_distress_score or 0.0, financial
        )
        existing.drug_signal_score = max(existing.drug_signal_score or 0.0, substance)
        existing.violence_score = max(existing.violence_score or 0.0, aggression)
        existing.last_assessed_at = datetime.now(timezone.utc)
    else:
        bp = BehaviouralProfile(
            id=uuid.uuid4(),
            person_id=person_id,
            gambling_score=gambling,
            financial_distress_score=financial,
            fraud_score=0.0,
            drug_signal_score=substance,
            violence_score=aggression,
            criminal_signal_score=0.0,
            last_assessed_at=datetime.now(timezone.utc),
        )
        session.add(bp)
