"""
timeline_builder.py — On-demand timeline assembler.

Reads from all source tables (criminal_records, employment_history, education,
addresses, properties, family_tree, social_profiles, adverse_media,
pep_classifications, watchlist_matches, breach_records, travel_history) and
writes TimelineEvent rows for a given person.

Deduplicates on (person_id, event_type, event_date). Returns the count of
newly created events.

Usage:
    async with AsyncSessionLocal() as session:
        count = await TimelineBuilder().build(person_id, session)
        await session.commit()
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.address import Address
from shared.models.breach import BreachRecord
from shared.models.compliance_ext import AdverseMedia, PepClassification
from shared.models.criminal import CriminalRecord
from shared.models.education import Education
from shared.models.employment import EmploymentHistory
from shared.models.property import Property
from shared.models.social_profile import SocialProfile
from shared.models.timeline import TimelineEvent
from shared.models.watchlist import WatchlistMatch

logger = logging.getLogger(__name__)


def _to_date(value: date | datetime | str | None) -> date | None:
    """Normalise a value to a plain date or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


class TimelineBuilder:
    """Assembles a person's full chronological timeline from all source tables."""

    async def build(self, person_id: uuid.UUID, session: AsyncSession) -> int:
        """Build timeline for *person_id*. Returns count of new events created."""
        event_dicts: list[dict] = []

        # Gather from all source tables
        event_dicts.extend(await self._events_from_criminal(session, person_id))
        event_dicts.extend(await self._events_from_employment(session, person_id))
        event_dicts.extend(await self._events_from_education(session, person_id))
        event_dicts.extend(await self._events_from_addresses(session, person_id))
        event_dicts.extend(await self._events_from_properties(session, person_id))
        event_dicts.extend(await self._events_from_social_profiles(session, person_id))
        event_dicts.extend(await self._events_from_adverse_media(session, person_id))
        event_dicts.extend(await self._events_from_pep(session, person_id))
        event_dicts.extend(await self._events_from_watchlist(session, person_id))
        event_dicts.extend(await self._events_from_breaches(session, person_id))
        event_dicts.extend(await self._events_from_travel(session, person_id))

        created = 0
        for ev in event_dicts:
            if ev.get("event_date") is None:
                continue  # skip events with no date — not useful in a timeline
            is_new = await self._upsert_event(
                session=session,
                person_id=person_id,
                event_type=ev["event_type"],
                event_date=ev["event_date"],
                title=ev.get("title", ""),
                description=ev.get("description"),
                confidence=ev.get("confidence", 0.5),
                source_type=ev.get("source_type"),
                source_platform=ev.get("source_platform"),
                location=ev.get("location"),
                meta=ev.get("meta", {}),
            )
            if is_new:
                created += 1

        logger.info(
            "TimelineBuilder: person_id=%s — %d new events (from %d candidates)",
            person_id, created, len(event_dicts),
        )
        return created

    # ── Source extractors ─────────────────────────────────────────────────────

    async def _events_from_criminal(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(CriminalRecord).where(CriminalRecord.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            # Arrest event
            arrest_date = _to_date(r.arrest_date)
            if arrest_date:
                events.append({
                    "event_type": "criminal_arrest",
                    "event_date": arrest_date,
                    "title": f"Arrest: {r.charge or 'Unknown charge'}",
                    "description": r.offense_description,
                    "location": r.jurisdiction,
                    "source_type": "court_record",
                    "source_platform": r.source_platform,
                    "confidence": 0.85,
                    "meta": {
                        "record_id": str(r.id),
                        "offense_level": r.offense_level,
                        "court_case_number": r.court_case_number,
                        "court_name": r.court_name,
                    },
                })

            # Charge event
            charge_date = _to_date(r.charge_date)
            if charge_date:
                events.append({
                    "event_type": "criminal_charge",
                    "event_date": charge_date,
                    "title": f"Charged: {r.charge or 'Unknown charge'}",
                    "description": r.offense_description,
                    "location": r.jurisdiction,
                    "source_type": "court_record",
                    "source_platform": r.source_platform,
                    "confidence": 0.85,
                    "meta": {
                        "record_id": str(r.id),
                        "offense_level": r.offense_level,
                        "statute": r.statute,
                        "court_case_number": r.court_case_number,
                    },
                })

            # Conviction / disposition event
            disposition_date = _to_date(r.disposition_date)
            if disposition_date and r.disposition:
                ev_type = (
                    "criminal_conviction"
                    if r.disposition in ("guilty", "plea_deal")
                    else "criminal_charge"
                )
                events.append({
                    "event_type": ev_type,
                    "event_date": disposition_date,
                    "title": f"Disposition ({r.disposition}): {r.charge or 'Unknown charge'}",
                    "description": r.sentence,
                    "location": r.jurisdiction,
                    "source_type": "court_record",
                    "source_platform": r.source_platform,
                    "confidence": 0.90,
                    "meta": {
                        "record_id": str(r.id),
                        "disposition": r.disposition,
                        "sentence_months": r.sentence_months,
                        "fine_usd": r.fine_usd,
                    },
                })

            # Warrant
            warrant_date = _to_date(r.warrant_date)
            if warrant_date:
                events.append({
                    "event_type": "criminal_warrant",
                    "event_date": warrant_date,
                    "title": f"Warrant issued: {r.charge or 'Unknown charge'}",
                    "description": r.offense_description,
                    "location": r.jurisdiction,
                    "source_type": "court_record",
                    "source_platform": r.source_platform,
                    "confidence": 0.80,
                    "meta": {"record_id": str(r.id)},
                })

        return events

    async def _events_from_employment(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(EmploymentHistory).where(EmploymentHistory.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            started = _to_date(r.started_at)
            ended = _to_date(r.ended_at)

            if started:
                events.append({
                    "event_type": "employment_start",
                    "event_date": started,
                    "title": f"Started: {r.job_title or 'Role'} at {r.employer_name or 'Unknown employer'}",
                    "description": (
                        f"Industry: {r.industry}"
                        if r.industry
                        else None
                    ),
                    "location": r.location,
                    "source_type": "employment_record",
                    "source_platform": None,
                    "confidence": 0.75,
                    "meta": {
                        "employment_id": str(r.id),
                        "estimated_salary_usd": r.estimated_salary_usd,
                    },
                })

            if ended:
                events.append({
                    "event_type": "employment_end",
                    "event_date": ended,
                    "title": f"Left: {r.job_title or 'Role'} at {r.employer_name or 'Unknown employer'}",
                    "description": None,
                    "location": r.location,
                    "source_type": "employment_record",
                    "source_platform": None,
                    "confidence": 0.70,
                    "meta": {"employment_id": str(r.id)},
                })

        return events

    async def _events_from_education(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(Education).where(Education.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            started = _to_date(r.started_at)
            ended = _to_date(r.ended_at)

            if started:
                events.append({
                    "event_type": "education_start",
                    "event_date": started,
                    "title": f"Enrolled: {r.degree or 'Programme'} at {r.institution or 'Unknown institution'}",
                    "description": r.field_of_study,
                    "location": None,
                    "source_type": "education_record",
                    "source_platform": None,
                    "confidence": 0.70,
                    "meta": {"education_id": str(r.id), "tier": r.tier},
                })

            if ended and r.is_completed:
                events.append({
                    "event_type": "education_graduation",
                    "event_date": ended,
                    "title": f"Graduated: {r.degree or 'Programme'} from {r.institution or 'Unknown institution'}",
                    "description": r.field_of_study,
                    "location": None,
                    "source_type": "education_record",
                    "source_platform": None,
                    "confidence": 0.75,
                    "meta": {"education_id": str(r.id)},
                })

        return events

    async def _events_from_addresses(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        """Generate address_change events using created_at as the move-in date."""
        result = await session.execute(
            select(Address)
            .where(Address.person_id == person_id)
            .order_by(Address.created_at.asc())
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            move_date = _to_date(r.created_at)
            if not move_date:
                continue
            parts = [
                p for p in [r.street, r.city, r.state_province, r.country] if p
            ]
            address_str = ", ".join(parts) if parts else "Unknown address"
            events.append({
                "event_type": "address_change",
                "event_date": move_date,
                "title": f"Address: {address_str}",
                "description": f"Type: {r.address_type}",
                "location": address_str,
                "source_type": "government",
                "source_platform": None,
                "confidence": 0.65,
                "meta": {
                    "address_id": str(r.id),
                    "address_type": r.address_type,
                    "is_current": r.is_current,
                },
            })

        return events

    async def _events_from_properties(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(Property).where(Property.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            purchase_date = _to_date(r.last_sale_date)
            if purchase_date:
                addr = r.street_address or f"{r.city}, {r.state}" if r.city else "Unknown property"
                events.append({
                    "event_type": "property_purchase",
                    "event_date": purchase_date,
                    "title": f"Property acquired: {addr}",
                    "description": (
                        f"Type: {r.property_type or 'unknown'}. "
                        f"Value: ${r.last_sale_price_usd:,.0f}"
                        if r.last_sale_price_usd
                        else f"Type: {r.property_type or 'unknown'}"
                    ),
                    "location": addr,
                    "source_type": "property_record",
                    "source_platform": None,
                    "confidence": 0.85,
                    "meta": {
                        "property_id": str(r.id),
                        "parcel_number": r.parcel_number,
                        "last_sale_price_usd": r.last_sale_price_usd,
                        "last_sale_type": r.last_sale_type,
                    },
                })

        return events

    async def _events_from_social_profiles(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(SocialProfile).where(SocialProfile.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            created = _to_date(r.profile_created_at)
            if not created:
                continue
            handle_str = f"@{r.handle}" if r.handle else r.display_name or "account"
            events.append({
                "event_type": "social_profile_created",
                "event_date": created,
                "title": f"{r.platform} profile created: {handle_str}",
                "description": r.bio,
                "location": None,
                "source_type": "social_media",
                "source_platform": r.platform,
                "confidence": 0.80,
                "meta": {
                    "social_profile_id": str(r.id),
                    "platform": r.platform,
                    "is_verified": r.is_verified,
                    "follower_count": r.follower_count,
                },
            })

        return events

    async def _events_from_adverse_media(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(AdverseMedia).where(
                AdverseMedia.person_id == person_id,
                AdverseMedia.is_retracted.is_(False),
            )
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            pub_date = _to_date(r.publication_date)
            if not pub_date:
                continue
            # Confidence tracks with severity
            _severity_confidence = {
                "critical": 0.90, "high": 0.80, "medium": 0.65, "low": 0.50
            }
            events.append({
                "event_type": "adverse_media",
                "event_date": pub_date,
                "title": r.headline or f"Adverse media ({r.severity})",
                "description": r.summary,
                "location": None,
                "source_type": "news_media",
                "source_platform": r.source_name,
                "confidence": _severity_confidence.get(r.severity, 0.65),
                "meta": {
                    "adverse_media_id": str(r.id),
                    "category": r.category,
                    "severity": r.severity,
                    "url_hash": r.url_hash,
                    "source_country": r.source_country,
                    "is_verified": r.is_verified,
                },
            })

        return events

    async def _events_from_pep(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(PepClassification).where(PepClassification.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            start = _to_date(r.start_date)
            if not start:
                continue
            position_str = r.position_title or "Official"
            org_str = f" — {r.organization}" if r.organization else ""
            events.append({
                "event_type": "pep_appointment",
                "event_date": start,
                "title": f"PEP Appointment: {position_str}{org_str}",
                "description": (
                    f"Level: {r.pep_level}. Category: {r.pep_category}. "
                    f"Country: {r.country or 'unknown'}."
                ),
                "location": r.jurisdiction or r.country,
                "source_type": "pep_database",
                "source_platform": r.source_platform,
                "confidence": r.confidence,
                "meta": {
                    "pep_classification_id": str(r.id),
                    "pep_level": r.pep_level,
                    "pep_category": r.pep_category,
                    "is_current": r.is_current,
                    "end_date": r.end_date.isoformat() if r.end_date else None,
                },
            })

        return events

    async def _events_from_watchlist(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(WatchlistMatch).where(WatchlistMatch.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            listed = _to_date(r.listed_date)
            if not listed:
                listed = _to_date(r.created_at)
            if not listed:
                continue
            events.append({
                "event_type": "watchlist_listed",
                "event_date": listed,
                "title": f"Watchlist match: {r.list_name}",
                "description": r.reason,
                "location": None,
                "source_type": "government_registry",
                "source_platform": r.list_name,
                "confidence": r.match_score,
                "meta": {
                    "watchlist_match_id": str(r.id),
                    "list_type": r.list_type,
                    "match_name": r.match_name,
                    "is_confirmed": r.is_confirmed,
                },
            })

        return events

    async def _events_from_breaches(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        result = await session.execute(
            select(BreachRecord).where(BreachRecord.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            breach_date = _to_date(r.breach_date)
            if not breach_date:
                breach_date = _to_date(r.created_at)
            if not breach_date:
                continue
            fields_str = (
                ", ".join(r.exposed_fields[:5])
                if r.exposed_fields
                else "unknown fields"
            )
            events.append({
                "event_type": "breach_exposure",
                "event_date": breach_date,
                "title": f"Data breach: {r.breach_name}",
                "description": f"Exposed fields: {fields_str}. Severity: {r.severity}.",
                "location": None,
                "source_type": "breach_database",
                "source_platform": r.source_type,
                "confidence": 0.80,
                "meta": {
                    "breach_record_id": str(r.id),
                    "severity": r.severity,
                    "exposed_fields": list(r.exposed_fields or []),
                },
            })

        return events

    async def _events_from_travel(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> list[dict]:
        """Import TravelHistory inline to avoid circular import issues."""
        from shared.models.timeline import TravelHistory

        result = await session.execute(
            select(TravelHistory).where(TravelHistory.person_id == person_id)
        )
        records = result.scalars().all()
        events: list[dict] = []

        for r in records:
            travel_date = _to_date(r.travel_date)
            if not travel_date:
                continue
            dest = r.arrival_city or r.arrival_country or "unknown destination"
            origin = r.departure_city or r.departure_country or "unknown origin"
            events.append({
                "event_type": "travel",
                "event_date": travel_date,
                "title": f"Travel: {origin} → {dest}",
                "description": (
                    f"Mode: {r.travel_mode or 'unknown'}. "
                    f"Carrier: {r.carrier or 'unknown'}."
                    + (f" FLAGGED: {r.flag_reason}" if r.is_flagged and r.flag_reason else "")
                ),
                "location": dest,
                "source_type": "government",
                "source_platform": r.source_platform,
                "confidence": r.confidence,
                "meta": {
                    "travel_id": str(r.id),
                    "departure_country": r.departure_country,
                    "arrival_country": r.arrival_country,
                    "travel_mode": r.travel_mode,
                    "is_flagged": r.is_flagged,
                    "visa_type": r.visa_type,
                },
            })

        return events

    # ── Upsert single event ───────────────────────────────────────────────────

    async def _upsert_event(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        event_type: str,
        event_date: date,
        title: str,
        description: str | None,
        confidence: float,
        source_type: str | None,
        source_platform: str | None,
        location: str | None = None,
        meta: dict | None = None,
    ) -> bool:
        """Upsert a timeline event. Returns True if newly created, False if duplicate.

        Deduplicates on (person_id, event_type, event_date). On conflict, updates
        title, description, confidence and source fields if the new record has
        higher confidence.
        """
        result = await session.execute(
            select(TimelineEvent).where(
                TimelineEvent.person_id == person_id,
                TimelineEvent.event_type == event_type,
                TimelineEvent.event_date == event_date,
            ).limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update only if this version is more confident
            if confidence > existing.confidence:
                existing.title = title or existing.title
                existing.description = description or existing.description
                existing.confidence = confidence
                existing.source_type = source_type or existing.source_type
                existing.source_platform = source_platform or existing.source_platform
                existing.location = location or existing.location
                if meta:
                    merged = dict(existing.meta or {})
                    merged.update(meta)
                    existing.meta = merged
            return False

        event = TimelineEvent(
            person_id=person_id,
            event_date=event_date,
            event_type=event_type,
            title=title,
            description=description,
            location=location,
            source_type=source_type,
            source_platform=source_platform,
            confidence=confidence,
            related_person_ids=[],
            related_entity_ids=[],
            meta=meta or {},
        )
        session.add(event)
        return True
