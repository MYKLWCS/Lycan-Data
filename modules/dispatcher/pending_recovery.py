"""
PendingJobRecovery — rescues crawl jobs stuck in 'pending' state.

Jobs land in 'pending' when the dispatcher dequeues them from Redis but
drops them before execution (e.g. burst overload, pool exhaustion, restart).
This daemon scans every 5 minutes for jobs older than 3 minutes that are
still 'pending', re-enqueues them, and marks them as recovered in meta.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone, datetime, timedelta

from sqlalchemy import select

from shared.constants import CrawlStatus
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.crawl import CrawlJob

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 300       # seconds between scans
STALE_THRESHOLD = 180     # jobs pending > 3 minutes are considered dropped
MAX_RECOVER_PER_SCAN = 50


class PendingJobRecovery:
    """Background daemon that re-queues stale pending crawl jobs."""

    def __init__(self) -> None:
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("PendingJobRecovery daemon started")
        while self._running:
            try:
                await self._recover_stale()
            except Exception as exc:
                logger.exception("PendingJobRecovery error: %s", exc)
            await asyncio.sleep(SCAN_INTERVAL)

    async def stop(self) -> None:
        self._running = False

    async def _recover_stale(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CrawlJob)
                .where(
                    CrawlJob.status == CrawlStatus.PENDING.value,
                    CrawlJob.created_at < cutoff,
                )
                .limit(MAX_RECOVER_PER_SCAN)
            )
            stale_jobs = result.scalars().all()

        if not stale_jobs:
            return

        recovered = 0
        for job in stale_jobs:
            try:
                platform = (job.meta or {}).get("platform", "")
                identifier = job.seed_identifier or ""
                person_id = str(job.person_id) if job.person_id else None

                if not platform or not identifier:
                    continue

                payload = {
                    "job_id": str(job.id),
                    "platform": platform,
                    "identifier": identifier,
                    "person_id": person_id,
                    "retry_count": 0,
                }
                await event_bus.enqueue(payload, priority="normal")
                recovered += 1

            except Exception as exc:
                logger.warning("Failed to recover job %s: %s", job.id, exc)

        if recovered:
            logger.info("PendingJobRecovery: re-queued %d stale jobs", recovered)
