"""
Freshness Scheduler.

Runs every N minutes. Queries all tables with DataQualityMixin for rows
where freshness_score < threshold. Inserts them into FreshnessQueue.
The dispatcher picks up FreshnessQueue items as low-priority crawl jobs.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from modules.dispatcher.dispatcher import dispatch_job
from shared.config import settings
from shared.db import AsyncSessionLocal
from shared.models.quality import FreshnessQueue
from shared.models.social_profile import SocialProfile

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 300  # scan every 5 minutes
BATCH_SIZE = 100  # process 100 stale records per scan


class FreshnessScheduler:
    def __init__(self):
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Freshness scheduler started")
        while self._running:
            try:
                await self._scan_and_queue()
            except Exception as exc:
                logger.exception(f"Scheduler error: {exc}")
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False

    async def _scan_and_queue(self) -> None:
        """Scan for stale records and enqueue re-scrape jobs."""
        stale_count = 0
        async with AsyncSessionLocal() as session:
            stale_profiles = await self._find_stale_profiles(session)
            for profile in stale_profiles:
                queued = await self._enqueue_rescrape(session, profile)
                if queued:
                    stale_count += 1
            await session.commit()

        if stale_count:
            logger.info(f"Freshness scheduler: queued {stale_count} re-scrape jobs")

    async def _find_stale_profiles(self, session) -> list[SocialProfile]:
        """Find SocialProfile records with low freshness score."""
        result = await session.execute(
            select(SocialProfile)
            .where(SocialProfile.freshness_score < settings.freshness_threshold)
            .where(SocialProfile.last_scraped_at.isnot(None))
            .order_by(SocialProfile.freshness_score.asc())
            .limit(BATCH_SIZE)
        )
        return result.scalars().all()

    async def _enqueue_rescrape(self, session, profile: SocialProfile) -> bool:
        """Add to FreshnessQueue and dispatch low-priority job. Returns True if enqueued."""
        # Check if already queued
        existing = await session.execute(
            select(FreshnessQueue)
            .where(
                FreshnessQueue.record_id == str(profile.id),
                FreshnessQueue.table_name == "social_profiles",
            )
            .limit(1)
        )
        if existing.scalar():
            return False

        # Add to freshness queue
        fq = FreshnessQueue(
            table_name="social_profiles",
            record_id=str(profile.id),
            current_freshness=profile.freshness_score or 0.0,
            source_type=profile.platform,
            scheduled_at=datetime.now(UTC),
        )
        session.add(fq)

        # Dispatch low-priority crawl job
        if settings.rescrape_on_staleness and profile.handle:
            await dispatch_job(
                platform=profile.platform,
                identifier=profile.handle,
                person_id=str(profile.person_id) if profile.person_id else None,
                priority="low",
            )

        return True


freshness_scheduler = FreshnessScheduler()
