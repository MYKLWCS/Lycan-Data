"""
Crawl Job Dispatcher.

Pulls CrawlJob messages from Dragonfly priority queues (high -> normal -> low),
looks up the registered crawler for the platform, runs it, writes results to DB,
updates CrawlJob status, and emits completion events.

Each dispatcher worker runs up to CONCURRENCY_PER_WORKER jobs in parallel using
an asyncio.Semaphore so one slow/failed scraper never blocks the others.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.crawlers.registry import get_crawler
from shared.constants import CrawlStatus
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.crawl import CrawlJob, CrawlLog
from shared.schemas.progress import EventType

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [30, 120, 300]  # seconds: 30s, 2min, 5min
CONCURRENCY_PER_WORKER = 10  # max parallel scrapers per dispatcher worker


class CrawlDispatcher:
    """Concurrent dispatcher. Runs up to CONCURRENCY_PER_WORKER jobs in parallel."""

    def __init__(self, worker_id: str = "worker-1", concurrency: int = CONCURRENCY_PER_WORKER):
        self.worker_id = worker_id
        self._running = False
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Start the concurrent dispatch loop."""
        self._running = True
        logger.info(
            "Dispatcher %s started (concurrency=%d)",
            self.worker_id,
            self._semaphore._value,
        )
        while self._running:
            try:
                # Wait for a concurrency slot before dequeuing
                await self._semaphore.acquire()
                raw = await event_bus.dequeue_any(timeout=2)
                if raw is None:
                    self._semaphore.release()
                    continue

                # Spawn concurrent task
                task = asyncio.create_task(
                    self._process_one_guarded(raw),
                    name=f"{self.worker_id}-job",
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._semaphore.release()
                logger.exception("Dispatcher %s loop error: %s", self.worker_id, exc)
                await asyncio.sleep(1)

        # Drain in-flight tasks on shutdown
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False

    async def _process_one_guarded(self, raw) -> None:
        """Run a single job inside the semaphore guard, releasing on completion."""
        try:
            await self._process_one(raw)
        except Exception as exc:
            logger.exception("Dispatcher %s job error: %s", self.worker_id, exc)
        finally:
            self._semaphore.release()

    async def _process_one(self, raw) -> None:
        """Parse and route one job payload."""
        if isinstance(raw, dict):
            job_dict = raw
        else:
            try:
                job_dict = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid job payload: %r", raw)
                return

        job_id = job_dict.get("job_id")
        platform = job_dict.get("platform", "").lower()
        identifier = job_dict.get("identifier", "")
        person_id = job_dict.get("person_id")
        retry_count = job_dict.get("retry_count", 0)

        async with AsyncSessionLocal() as session:
            await self._run_job(
                session, job_id, platform, identifier, person_id, retry_count, job_dict
            )

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
            logger.warning("No crawler for platform: %s", platform)
            await self._update_job_status(
                session, job_id, CrawlStatus.FAILED, f"No crawler for: {platform}"
            )
            return

        await self._update_job_status(session, job_id, CrawlStatus.RUNNING)
        started_at = datetime.now(UTC)

        # Emit scraper_running progress event
        await self._emit_progress(person_id, EventType.SCRAPER_RUNNING, platform)

        try:
            crawler = crawler_cls()
            result = await crawler.run(identifier)

            duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)

            if result.found:
                # ── DECOUPLED: Push to Ingest Queue ──
                ingest_payload = {
                    "result": result.to_db_dict()
                    if hasattr(result, "to_db_dict")
                    else result.__dict__,
                    "platform": result.platform,
                    "identifier": result.identifier,
                    "found": result.found,
                    "error": result.error,
                    "person_id": person_id,
                    "source_reliability": result.source_reliability,
                }
                if hasattr(result, "data"):
                    ingest_payload["data"] = result.data

                await event_bus.enqueue(ingest_payload, priority="ingest")

                await self._update_job_status(session, job_id, CrawlStatus.DONE)
                await self._log_crawl(session, job_id, platform, identifier, True, duration_ms)
                await event_bus.publish(
                    "enrichment",
                    {
                        "event": "crawl_complete",
                        "platform": platform,
                        "identifier": identifier,
                        "person_id": person_id,
                        "found": True,
                    },
                )
                # Emit scraper_done with result count
                data = ingest_payload.get("data") or {}
                results_found = len(data) if isinstance(data, list) else (1 if data else 0)
                await self._emit_progress(
                    person_id, EventType.SCRAPER_DONE, platform, results_found=results_found
                )
            else:
                if result.error and "rate" in (result.error or "").lower():
                    await self._requeue_with_backoff(job_dict, retry_count)
                    await self._update_job_status(session, job_id, CrawlStatus.RATE_LIMITED)
                elif result.error and "block" in (result.error or "").lower():
                    await self._update_job_status(session, job_id, CrawlStatus.BLOCKED)
                else:
                    await self._update_job_status(session, job_id, CrawlStatus.DONE)
                await self._log_crawl(
                    session, job_id, platform, identifier, False, duration_ms, result.error
                )
                await self._emit_progress(person_id, EventType.SCRAPER_DONE, platform)

            # Check if all jobs for this person are complete
            await self._check_search_complete(session, person_id, started_at)

        except Exception as exc:
            logger.exception("Job %s failed: %s", job_id, exc)
            if retry_count < MAX_RETRIES:
                await self._requeue_with_backoff(job_dict, retry_count)
            await self._update_job_status(session, job_id, CrawlStatus.FAILED, str(exc))
            await self._emit_progress(
                person_id, EventType.SCRAPER_FAILED, platform, error=str(exc)
            )
            # Check if all jobs for this person are complete (even after failure)
            await self._check_search_complete(session, person_id, started_at)

    async def _emit_progress(
        self,
        person_id: str | None,
        event_type: str,
        platform: str,
        results_found: int = 0,
        error: str | None = None,
    ) -> None:
        """Publish a scraper progress event to the progress channel (fire-and-forget)."""
        if not person_id or not event_bus.is_connected:
            return
        try:
            await event_bus.publish(
                "progress",
                {
                    "event_type": event_type,
                    "search_id": person_id,
                    "scraper_name": platform,
                    "results_found": results_found,
                    "error": error,
                },
            )
        except Exception:
            pass  # Never let progress emission crash the job

    async def _check_search_complete(
        self,
        session: AsyncSession,
        person_id: str | None,
        search_started_at: datetime,
    ) -> None:
        """Check if all crawl jobs for a person are terminal. If so, emit SEARCH_COMPLETE."""
        if not person_id or not event_bus.is_connected:
            return
        try:
            from sqlalchemy import func, select

            # Count jobs still in non-terminal states
            pending_count = (
                await session.execute(
                    select(func.count())
                    .select_from(CrawlJob)
                    .where(
                        CrawlJob.person_id == person_id,
                        CrawlJob.status.in_([
                            CrawlStatus.PENDING.value,
                            CrawlStatus.RUNNING.value,
                        ]),
                    )
                )
            ).scalar() or 0

            if pending_count > 0:
                return

            # All jobs finished — gather summary stats
            from sqlalchemy import case, literal_column

            stats = (
                await session.execute(
                    select(
                        func.count().label("total"),
                        func.count(
                            case(
                                (CrawlJob.status == CrawlStatus.DONE.value, literal_column("1")),
                            )
                        ).label("succeeded"),
                        func.count(
                            case(
                                (CrawlJob.status == CrawlStatus.FAILED.value, literal_column("1")),
                            )
                        ).label("failed"),
                    )
                    .select_from(CrawlJob)
                    .where(CrawlJob.person_id == person_id)
                )
            ).mappings().one()

            duration = (datetime.now(UTC) - search_started_at).total_seconds()

            await event_bus.publish(
                "progress",
                {
                    "event_type": EventType.SEARCH_COMPLETE,
                    "search_id": person_id,
                    "total_scrapers": int(stats["total"] or 0),
                    "succeeded": int(stats["succeeded"] or 0),
                    "failed": int(stats["failed"] or 0),
                    "duration_seconds": round(duration, 1),
                },
            )
            logger.info("SEARCH_COMPLETE emitted for person_id=%s", person_id)
        except Exception:
            logger.exception("Failed to check/emit search_complete for %s", person_id)

    async def _update_job_status(
        self,
        session: AsyncSession,
        job_id: str | None,
        status: CrawlStatus,
        error: str | None = None,
    ) -> None:
        if not job_id:
            return
        from sqlalchemy import update

        await session.execute(
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(status=status.value, error_message=error, updated_at=datetime.now(UTC))
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
        """Write a CrawlLog entry. Skips if job_id is None (job_id is NOT NULL)."""
        if not job_id:
            return
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
        job_dict["run_after"] = datetime.now(UTC).timestamp() + delay
        priority = "low" if retry_count >= 1 else "normal"
        await event_bus.enqueue(job_dict, priority=priority)
        logger.info("Requeued job with %ds backoff (retry %d)", delay, retry_count + 1)


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
