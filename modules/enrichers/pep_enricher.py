"""
pep_enricher.py — Async daemon that checks persons against PEP (Politically
Exposed Person) lists and persists classification records.

Polls every 2 hours. Targets persons whose pep_status key is absent from
Person.meta, or whose PEP check is older than 7 days. Runs two crawlers
(open_pep_search, world_check_mirror) and writes PepClassification rows.
Updates Person.meta["pep_status"] and Person.meta["pep_level"]. Creates a
TimelineEvent for each confirmed PEP appointment found.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timezone, datetime, timedelta

from sqlalchemy import DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.enrichers.timeline_builder import TimelineBuilder
from shared.db import AsyncSessionLocal
from shared.models.compliance_ext import PepClassification
from shared.models.person import Person

logger = logging.getLogger(__name__)

_SLEEP_INTERVAL = 7200  # 2 hours
_BATCH_SIZE = 30
_STALE_THRESHOLD_DAYS = 7

# PEP level hierarchy for choosing the highest confirmed level
_LEVEL_RANK: dict[str, int] = {
    "tier1": 4,
    "tier2": 3,
    "tier3": 2,
    "family": 1,
    "associate": 0,
}


class PepEnricher:
    """Continuously checks persons against PEP databases."""

    def __init__(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        """Entry point — runs forever with 2-hour sleep between batches."""
        logger.info("PepEnricher started (interval=%ds)", _SLEEP_INTERVAL)
        while self._running:
            try:
                await self._process_pending()
            except Exception as exc:
                logger.exception("PepEnricher batch error: %s", exc)
            await asyncio.sleep(_SLEEP_INTERVAL)

    # ── Batch selection ───────────────────────────────────────────────────────

    async def _process_pending(self) -> None:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=_STALE_THRESHOLD_DAYS)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Person.id)
                .where(
                    (~Person.meta.has_key("pep_status"))
                    | (~Person.meta.has_key("pep_checked_at"))
                    | (Person.meta["pep_checked_at"].astext.cast(DateTime) < stale_cutoff)
                )
                .limit(_BATCH_SIZE)
            )
            person_ids = [row[0] for row in result.fetchall()]

        logger.info("PepEnricher: %d persons to check", len(person_ids))
        for pid in person_ids:
            try:
                async with AsyncSessionLocal() as session:
                    await self.check_person(pid, session)
                    await session.commit()
            except Exception as exc:
                logger.exception("PepEnricher: failed person_id=%s — %s", pid, exc)

    # ── Per-person check ──────────────────────────────────────────────────────

    async def check_person(self, person_id: uuid.UUID, session: AsyncSession) -> None:
        """Run PEP crawlers for one person and persist any matches found."""
        from modules.crawlers.pep.open_pep_search import OpenPepSearchCrawler
        from modules.crawlers.pep.world_check_mirror import WorldCheckMirrorCrawler

        person = await session.get(Person, person_id)
        if not person:
            logger.warning("PepEnricher: person_id=%s not found", person_id)
            return

        identifier = person.full_name or str(person_id)
        crawlers = [OpenPepSearchCrawler(), WorldCheckMirrorCrawler()]

        pep_matches: list[dict] = []
        for crawler in crawlers:
            try:
                r = await crawler.scrape(identifier)
                if not r or not r.found:
                    continue
                matches = r.data if isinstance(r.data, list) else [r.data]
                for match in matches:
                    if match.get("is_pep"):
                        pep_matches.append(match)
            except Exception as exc:
                logger.debug(
                    "PepEnricher: crawler %s failed for %s — %s",
                    type(crawler).__name__,
                    identifier,
                    exc,
                )

        is_pep = len(pep_matches) > 0
        highest_level: str | None = None

        for match in pep_matches:
            await self._persist_pep_record(session, person_id, match)
            level = match.get("pep_level", "tier3")
            if highest_level is None or _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(
                highest_level, 0
            ):
                highest_level = level

        # Update Person.meta
        meta = dict(person.meta or {})
        meta["pep_status"] = is_pep
        meta["pep_level"] = highest_level
        meta["pep_checked_at"] = datetime.now(timezone.utc).isoformat()
        meta["pep_match_count"] = len(pep_matches)
        person.meta = meta

        logger.info(
            "PepEnricher: person_id=%s — is_pep=%s level=%s matches=%d",
            person_id,
            is_pep,
            highest_level,
            len(pep_matches),
        )

        # Create timeline events for newly found appointments
        if pep_matches:
            await self._create_pep_timeline_events(session, person_id, pep_matches)

    # ── PEP record persistence ────────────────────────────────────────────────

    async def _persist_pep_record(
        self, session: AsyncSession, person_id: uuid.UUID, pep_match: dict
    ) -> PepClassification:
        """Upsert a PepClassification row.

        Keyed on (person_id, position_title, organization) to avoid duplicates
        from repeated crawls. Updates confidence and dates if already present.
        """
        position = pep_match.get("position_title")
        organization = pep_match.get("organization")
        source_platform = pep_match.get("source_platform")

        result = await session.execute(
            select(PepClassification)
            .where(
                PepClassification.person_id == person_id,
                PepClassification.position_title == position,
                PepClassification.organization == organization,
            )
            .limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update time-sensitive fields
            new_confidence = pep_match.get("confidence", existing.confidence)
            if new_confidence > existing.confidence:
                existing.confidence = new_confidence
            if pep_match.get("end_date") and not existing.end_date:
                existing.end_date = pep_match["end_date"]
                existing.is_current = False
                existing.is_former = True
            return existing

        pep_level = pep_match.get("pep_level", "tier3")
        pep_category = pep_match.get("pep_category", "government")

        record = PepClassification(
            person_id=person_id,
            pep_level=pep_level,
            pep_category=pep_category,
            position_title=position,
            organization=organization,
            country=pep_match.get("country"),
            jurisdiction=pep_match.get("jurisdiction"),
            start_date=pep_match.get("start_date"),
            end_date=pep_match.get("end_date"),
            is_current=bool(pep_match.get("is_current", True)),
            is_former=bool(pep_match.get("is_former", False)),
            related_to_pep_id=pep_match.get("related_to_pep_id"),
            relationship_to_pep=pep_match.get("relationship_to_pep"),
            source_platform=source_platform,
            source_url=pep_match.get("source_url"),
            confidence=float(pep_match.get("confidence", 0.7)),
            meta=pep_match.get("meta", {}),
        )
        session.add(record)
        await session.flush()
        return record

    # ── Timeline event creation ───────────────────────────────────────────────

    async def _create_pep_timeline_events(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        pep_matches: list[dict],
    ) -> None:
        """Create TimelineEvent records for PEP appointments.

        Deferred import avoids circular dependency with timeline_builder.
        """
        try:
            builder = TimelineBuilder()
            for match in pep_matches:
                start_date = match.get("start_date")
                if not start_date:
                    continue
                position = match.get("position_title", "Government Official")
                org = match.get("organization", "")
                title = f"PEP Appointment: {position}"
                if org:
                    title += f" — {org}"
                await builder._upsert_event(
                    session=session,
                    person_id=person_id,
                    event_type="pep_appointment",
                    event_date=start_date,
                    title=title,
                    description=(
                        f"Politically Exposed Person appointment recorded. "
                        f"Level: {match.get('pep_level', 'unknown')}. "
                        f"Category: {match.get('pep_category', 'unknown')}."
                    ),
                    confidence=float(match.get("confidence", 0.7)),
                    source_type="pep_database",
                    source_platform=match.get("source_platform", "open_pep_search"),
                )
        except Exception as exc:
            logger.debug("PepEnricher: timeline event creation failed — %s", exc)
