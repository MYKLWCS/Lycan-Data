"""
Ingestion Daemon.

Pulls raw crawler results from the 'ingest' queue on the EventBus.
Processes them using the database aggregator, and then pushes a signal
to the 'index' queue for Typesense to pick up asynchronously.
"""

import asyncio
import json
import logging

from sqlalchemy.exc import IntegrityError

from modules.crawlers.core.result import CrawlerResult
from modules.pipeline.aggregator import aggregate_result
from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator
from modules.pipeline.pivot_enricher import pivot_from_result
from shared.db import AsyncSessionLocal
from shared.events import event_bus

logger = logging.getLogger(__name__)

_orchestrator = EnrichmentOrchestrator()


class IngestionDaemon:
    """Consumes raw data payloads and writes to DB."""

    def __init__(self, worker_id: str = "ingester-1"):
        self.worker_id = worker_id
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info(f"Ingestion Daemon {self.worker_id} started")
        while self._running:
            try:
                await self._process_one()
            except Exception as exc:
                logger.exception(f"Ingestion Daemon loop error: {exc}")
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

    async def _process_one(self) -> None:
        raw = await event_bus.dequeue(priority="ingest", timeout=5)
        if raw is None:
            return

        if isinstance(raw, dict):
            payload = raw
        else:
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid ingest payload: {raw!r}")
                return

        # Reconstruct CrawlerResult from payload
        result_dict = payload.get("result", {})
        data = payload.get("data", {})
        platform = payload.get("platform")
        identifier = payload.get("identifier")
        found = payload.get("found", False)
        error = payload.get("error")
        person_id = payload.get("person_id")

        result = CrawlerResult(
            platform=platform,
            identifier=identifier,
            found=found,
            data=data,
            error=error,
            profile_url=result_dict.get("profile_url"),
            # Read from top-level first (set by dispatcher); fall back to nested result dict
            source_reliability=payload.get(
                "source_reliability", result_dict.get("source_reliability", 0.5)
            ),
        )

        async with AsyncSessionLocal() as session:
            try:
                written = await aggregate_result(session, result, person_id=person_id)
                # Note: aggregate_result commits internally if successful.

                try:
                    if event_bus.is_connected and person_id:
                        await event_bus.publish("progress", {
                            "event_type": "DEDUP_RUNNING",
                            "search_id": str(person_id),
                        })
                except Exception as e:
                    logger.debug("Event publish failed: %s", e)

                # Push to Index Queue
                pid = written.get("person_id")
                if pid:
                    await event_bus.enqueue({"person_id": pid}, priority="index")

                    # Pivot: extract email/phone/name from result and queue new searches
                    if data and found:
                        try:
                            n = await pivot_from_result(pid, platform, data)
                            if n:
                                logger.info(
                                    "Pivot queued %d new jobs from %s/%s", n, platform, identifier
                                )
                        except Exception as pivot_exc:
                            logger.warning("Pivot failed for %s: %s", pid, pivot_exc)

                    # Auto-enrich: compute risk scores, AML, burner, etc.
                    try:
                        async with AsyncSessionLocal() as enrich_session:
                            await _orchestrator.enrich_person(pid, enrich_session)
                    except Exception as enrich_exc:
                        logger.warning("Auto-enrichment failed for %s: %s", pid, enrich_exc)

            except IntegrityError as e:
                await session.rollback()
                logger.info("Duplicate data skipped for person %s: %s", person_id, e.orig)
            except Exception as e:
                logger.error(f"Error aggregating result for {platform}/{identifier}: {e}")
                await session.rollback()
