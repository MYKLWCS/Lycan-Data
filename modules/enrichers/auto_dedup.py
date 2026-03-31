"""
AutoDedupDaemon — background deduplication daemon.

Runs every 10 minutes. Scores recently-updated persons against existing
records and routes candidates:
  - similarity >= 0.85 → auto-merge (richer record wins)
  - similarity 0.70-0.84 → insert DedupReview for manual review
  - similarity < 0.70 → skip

All merges execute in a single transaction with full rollback on failure.
Both UUIDs are written to audit_log with action="auto_merge".
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.enrichers.deduplication import AsyncMergeExecutor, score_person_dedup
from shared.db import AsyncSessionLocal as AsyncSessionFactory
from shared.models.dedup_review import DedupReview
from shared.models.person import Person

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
AUTO_MERGE_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.70
BATCH_WINDOW_MINUTES = 10
SLEEP_INTERVAL_SECONDS = 600  # 10 minutes


class AutoDedupDaemon:
    """Continuously deduplicates recently-updated person records."""

    def __init__(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        """Entry point — runs forever, sleeping between batches."""
        logger.info("AutoDedupDaemon started (interval=%ds)", SLEEP_INTERVAL_SECONDS)
        while self._running:
            try:
                async with AsyncSessionFactory() as session:
                    await self._run_batch(session)
            except Exception:
                logger.exception("AutoDedupDaemon: unhandled error in batch — continuing")
            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)

    async def _run_batch(self, session: AsyncSession) -> None:
        """Process one batch of recently-updated persons."""
        cutoff = datetime.now(UTC) - timedelta(minutes=BATCH_WINDOW_MINUTES)

        result = await session.execute(
            select(Person).where(Person.updated_at >= cutoff).where(Person.merged_into.is_(None))
        )
        persons = result.scalars().all()

        if not persons:
            logger.debug("AutoDedupDaemon: no persons updated in last %dm", BATCH_WINDOW_MINUTES)
            return

        logger.info("AutoDedupDaemon: scanning %d recently-updated persons", len(persons))
        seen_pairs: set[frozenset] = set()

        for person in persons:
            try:
                candidates = await score_person_dedup(str(person.id), session)
            except Exception:
                logger.exception(
                    "AutoDedupDaemon: score_person_dedup failed person_id=%s", person.id
                )
                continue

            for candidate in candidates:
                pair = frozenset({candidate.id_a, candidate.id_b})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                score = candidate.similarity_score

                if score >= AUTO_MERGE_THRESHOLD:
                    await self._auto_merge(candidate, session)
                elif score >= REVIEW_THRESHOLD:
                    await self._queue_for_review(candidate, session)
                # else: skip silently

        await session.commit()

    async def _auto_merge(self, candidate, session: AsyncSession) -> None:
        """Determine canonical record and execute merge."""
        try:
            # Fetch both persons to compare richness
            result_a = await session.execute(select(Person).where(Person.id == candidate.id_a))
            result_b = await session.execute(select(Person).where(Person.id == candidate.id_b))
            person_a = result_a.scalar_one_or_none()
            person_b = result_b.scalar_one_or_none()

            if person_a is None or person_b is None:
                logger.warning(
                    "AutoDedupDaemon: person not found for pair %s / %s — skipping",
                    candidate.id_a,
                    candidate.id_b,
                )
                return

            count_a = await self._count_populated_fields(person_a, session)
            count_b = await self._count_populated_fields(person_b, session)

            if count_a >= count_b:
                canonical_id = str(person_a.id)
                duplicate_id = str(person_b.id)
            else:
                canonical_id = str(person_b.id)
                duplicate_id = str(person_a.id)

            plan = {"canonical_id": canonical_id, "duplicate_id": duplicate_id}
            result = await AsyncMergeExecutor().execute(plan, session)

            if result.get("merged"):
                logger.info(
                    "AutoDedupDaemon: auto-merged %s → %s (score=%.3f)",
                    duplicate_id,
                    canonical_id,
                    candidate.similarity_score,
                )
            else:
                logger.warning(
                    "AutoDedupDaemon: merge failed for %s → %s: %s",
                    duplicate_id,
                    canonical_id,
                    result.get("error"),
                )

        except Exception:
            logger.exception(
                "AutoDedupDaemon: _auto_merge failed for pair %s / %s",
                candidate.id_a,
                candidate.id_b,
            )

    async def _queue_for_review(self, candidate, session: AsyncSession) -> None:
        """Insert a DedupReview row for manual adjudication."""
        review = DedupReview(
            person_a_id=candidate.id_a,
            person_b_id=candidate.id_b,
            similarity_score=candidate.similarity_score,
        )
        session.add(review)
        logger.debug(
            "AutoDedupDaemon: queued review for %s / %s (score=%.3f)",
            candidate.id_a,
            candidate.id_b,
            candidate.similarity_score,
        )

    async def _count_populated_fields(self, person: Person, session: AsyncSession) -> int:
        """
        Sum non-null scalar fields on Person + count of child rows across
        identifiers, social_profiles, addresses, employment,
        criminal_records.

        Returns an integer richness score — higher means more data.
        """
        from shared.models.address import Address
        from shared.models.criminal import CriminalRecord
        from shared.models.identifier import Identifier
        from shared.models.social_profile import SocialProfile

        # Scalar field count (exclude id, uuid FK columns, and JSONB blobs)
        _SKIP = {"id", "meta", "data_quality", "merged_into"}
        scalar_count = sum(
            1
            for col in person.__table__.columns
            if col.name not in _SKIP and getattr(person, col.name, None) is not None
        )

        # Child row counts
        child_total = 0
        child_tables = [
            (Identifier, Identifier.person_id),
            (SocialProfile, SocialProfile.person_id),
            (Address, Address.person_id),
            (CriminalRecord, CriminalRecord.person_id),
        ]

        for Model, fk_col in child_tables:
            try:
                result = await session.execute(
                    select(func.count()).select_from(Model).where(fk_col == person.id)
                )
                child_total += result.scalar_one()
            except Exception:
                pass  # table may not exist in test env — non-fatal

        return scalar_count + child_total
