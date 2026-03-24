"""
Crawl Job Dispatcher.

Pulls CrawlJob messages from Dragonfly priority queues (high → normal → low),
looks up the registered crawler for the platform, runs it, writes results to DB,
updates CrawlJob status, and emits completion events.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.constants import CrawlStatus, Platform
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.crawl import CrawlJob, CrawlLog
from shared.models.person import Person
from shared.models.identifier import Identifier
from modules.crawlers.registry import get_crawler, CRAWLER_REGISTRY
from modules.pipeline.aggregator import aggregate_result
from modules.search.meili_indexer import meili_indexer, build_person_doc

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [30, 120, 300]  # seconds: 30s, 2min, 5min


class CrawlDispatcher:
    """Single-worker dispatcher. Run multiple instances for parallelism."""

    def __init__(self, worker_id: str = "worker-1"):
        self.worker_id = worker_id
        self._running = False

    async def start(self) -> None:
        """Start the dispatch loop."""
        self._running = True
        logger.info(f"Dispatcher {self.worker_id} started")
        while self._running:
            try:
                await self._process_one()
            except Exception as exc:
                logger.exception(f"Dispatcher loop error: {exc}")
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

    async def _process_one(self) -> None:
        """Dequeue one job (blocking with timeout), route to crawler, write results."""
        raw = await event_bus.dequeue_any(timeout=5)
        if raw is None:
            return

        if isinstance(raw, dict):
            job_dict = raw
        else:
            try:
                job_dict = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid job payload: {raw!r}")
                return

        job_id = job_dict.get("job_id")
        platform = job_dict.get("platform", "").lower()
        identifier = job_dict.get("identifier", "")
        person_id = job_dict.get("person_id")
        retry_count = job_dict.get("retry_count", 0)

        async with AsyncSessionLocal() as session:
            await self._run_job(session, job_id, platform, identifier, person_id, retry_count, job_dict)

    async def _run_job(
        self,
        session: AsyncSession,
        job_id: str | None,
        platform: str,
        identifier: str,
        person_id: str | None,
        retry_count: int,
        job_dict: dict,
    ) -> None:
        crawler_cls = get_crawler(platform)
        if crawler_cls is None:
            logger.warning(f"No crawler for platform: {platform}")
            await self._update_job_status(session, job_id, CrawlStatus.FAILED, f"No crawler for: {platform}")
            return

        await self._update_job_status(session, job_id, CrawlStatus.RUNNING)
        started_at = datetime.now(timezone.utc)

        try:
            crawler = crawler_cls()
            result = await crawler.run(identifier)

            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)

            if result.found:
                # ── DECOUPLED: Push to Ingest Queue ──
                ingest_payload = {
                    "result": result.to_db_dict() if hasattr(result, "to_db_dict") else result.__dict__,
                    "platform": result.platform,
                    "identifier": result.identifier,
                    "found": result.found,
                    "error": result.error,
                    "person_id": person_id,
                }
                # Fix nested dicts (to_db_dict might leave data intact)
                if hasattr(result, "data"):
                    ingest_payload["data"] = result.data

                await event_bus.enqueue(ingest_payload, priority="ingest")

                await self._update_job_status(session, job_id, CrawlStatus.DONE)
                await self._log_crawl(session, job_id, platform, identifier, True, duration_ms)
                await event_bus.publish("enrichment", {
                    "event": "crawl_complete",
                    "platform": platform,
                    "identifier": identifier,
                    "person_id": person_id,
                    "found": True,
                })
            else:
                if result.error and "rate" in (result.error or "").lower():
                    await self._requeue_with_backoff(job_dict, retry_count)
                    await self._update_job_status(session, job_id, CrawlStatus.RATE_LIMITED)
                elif result.error and "block" in (result.error or "").lower():
                    await self._update_job_status(session, job_id, CrawlStatus.BLOCKED)
                else:
                    await self._update_job_status(session, job_id, CrawlStatus.DONE)
                await self._log_crawl(session, job_id, platform, identifier, False, duration_ms, result.error)

        except Exception as exc:
            logger.exception(f"Job {job_id} failed: {exc}")
            if retry_count < MAX_RETRIES:
                await self._requeue_with_backoff(job_dict, retry_count)
            await self._update_job_status(session, job_id, CrawlStatus.FAILED, str(exc))

    async def _update_job_status(
        self, session: AsyncSession, job_id: str | None, status: CrawlStatus, error: str | None = None
    ) -> None:
        if not job_id:
            return
        from sqlalchemy import select, update
        from shared.models.crawl import CrawlJob
        await session.execute(
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(status=status.value, error_message=error, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()

    async def _log_crawl(
        self,
        session: AsyncSession,
        job_id: str | None,
        platform: str,
        identifier: str,
        success: bool,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        """Write a CrawlLog entry. Uses meta JSONB for platform/identifier/success."""
        log = CrawlLog(
            job_id=job_id,
            response_time_ms=duration_ms,
            error=error,
            meta={
                "platform": platform,
                "identifier": identifier,
                "success": success,
            },
        )
        session.add(log)
        await session.commit()

    async def _requeue_with_backoff(self, job_dict: dict, retry_count: int) -> None:
        delay = RETRY_DELAYS[min(retry_count, len(RETRY_DELAYS) - 1)]
        job_dict["retry_count"] = retry_count + 1
        job_dict["run_after"] = (datetime.now(timezone.utc).timestamp() + delay)
        priority = "low" if retry_count >= 1 else "normal"
        await event_bus.enqueue(job_dict, priority=priority)
        logger.info(f"Requeued job with {delay}s backoff (retry {retry_count + 1})")


async def dispatch_job(
    platform: str,
    identifier: str,
    person_id: str | None = None,
    priority: str = "normal",
    job_id: str | None = None,
) -> None:
    """Helper to enqueue a single crawl job."""
    payload = {
        "job_id": job_id,
        "platform": platform,
        "identifier": identifier,
        "person_id": person_id,
        "retry_count": 0,
    }
    await event_bus.enqueue(payload, priority=priority)
