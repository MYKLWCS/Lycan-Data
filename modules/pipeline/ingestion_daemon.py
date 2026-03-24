"""
Ingestion Daemon.

Pulls raw crawler results from the 'ingest' queue on the EventBus.
Processes them using the database aggregator, and then pushes a signal
to the 'index' queue for MeiliSearch to pick up asynchronously.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import AsyncSessionLocal
from shared.events import event_bus
from modules.crawlers.result import CrawlerResult
from modules.pipeline.aggregator import aggregate_result

logger = logging.getLogger(__name__)


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
            source_reliability=result_dict.get("source_reliability", 0.5),
        )

        async with AsyncSessionLocal() as session:
            try:
                written = await aggregate_result(session, result, person_id=person_id)
                # Note: aggregate_result commits internally if successful.
                
                # Push to Index Queue
                pid = written.get("person_id")
                if pid:
                    await event_bus.enqueue({"person_id": pid}, priority="index")
                    
            except Exception as e:
                logger.error(f"Error aggregating result for {platform}/{identifier}: {e}")
                await session.rollback()

