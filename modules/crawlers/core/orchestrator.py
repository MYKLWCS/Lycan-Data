"""
ScraperOrchestrator — runs all registered scrapers via asyncio.gather()
and streams results as they arrive.

Usage:
    orchestrator = ScraperOrchestrator()
    results = await orchestrator.run_all("John Doe")

    # Or stream:
    async for result in orchestrator.stream("John Doe"):
        process(result)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, UTC
from typing import Any, AsyncGenerator, Dict, List, Optional

from modules.crawlers.core.models import CrawlerCategory, CrawlerHealth

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """
    Runs registered scrapers concurrently and collects/streams results.

    Supports:
    - Running all scrapers or a filtered subset (by category/name)
    - Concurrent execution via asyncio.gather()
    - Streaming results as they arrive via asyncio.Queue
    - Health checks across all registered scrapers
    """

    def __init__(
        self,
        concurrency: int = 20,
        timeout: float = 120.0,
        categories: Optional[List[CrawlerCategory]] = None,
        platforms: Optional[List[str]] = None,
    ):
        self.concurrency = concurrency
        self.timeout = timeout
        self.categories = categories
        self.platforms = platforms
        self._semaphore = asyncio.Semaphore(concurrency)

    def _get_crawlers(self) -> list:
        """Get crawler instances filtered by category/platform."""
        from modules.crawlers.registry import CRAWLER_REGISTRY

        instances = []
        for name, cls in CRAWLER_REGISTRY.items():
            if self.platforms and name not in self.platforms:
                continue
            crawler = cls()
            if self.categories:
                crawler_cat = getattr(crawler, "category", None)
                if crawler_cat and crawler_cat not in self.categories:
                    continue
            instances.append(crawler)
        return instances

    async def run_all(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> list:
        """
        Run all matching scrapers concurrently via asyncio.gather().
        Returns flat list of results from all scrapers.
        """
        crawlers = self._get_crawlers()
        if not crawlers:
            logger.warning("No crawlers matched filters")
            return []

        logger.info(
            "Orchestrator launching %d scrapers for query=%r",
            len(crawlers),
            query,
        )

        async def _run_one(crawler):
            async with self._semaphore:
                t0 = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        crawler.run(query), timeout=self.timeout
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)
                    logger.info(
                        "orchestrator_done | scraper=%s elapsed_ms=%d found=%s",
                        crawler.platform,
                        elapsed,
                        getattr(result, "found", "?"),
                    )
                    return result
                except asyncio.TimeoutError:
                    logger.warning(
                        "orchestrator_timeout | scraper=%s timeout=%.0fs",
                        crawler.platform,
                        self.timeout,
                    )
                    return None
                except Exception as exc:
                    logger.error(
                        "orchestrator_error | scraper=%s error=%s",
                        crawler.platform,
                        exc,
                    )
                    return None

        results = await asyncio.gather(
            *[_run_one(c) for c in crawlers], return_exceptions=False
        )
        return [r for r in results if r is not None]

    async def stream(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator:
        """
        Stream results as each scraper finishes.
        Yields individual CrawlerResult objects.
        """
        queue: asyncio.Queue = asyncio.Queue()
        crawlers = self._get_crawlers()
        pending = len(crawlers)

        if not crawlers:
            return

        async def _run_and_enqueue(crawler):
            async with self._semaphore:
                try:
                    result = await asyncio.wait_for(
                        crawler.run(query), timeout=self.timeout
                    )
                    if result is not None:
                        await queue.put(result)
                except Exception as exc:
                    logger.warning(
                        "stream_error | scraper=%s error=%s",
                        crawler.platform,
                        exc,
                    )
                finally:
                    await queue.put(None)  # sentinel

        tasks = [
            asyncio.create_task(_run_and_enqueue(c)) for c in crawlers
        ]

        done_count = 0
        while done_count < pending:
            item = await queue.get()
            if item is None:
                done_count += 1
            else:
                yield item

        # Ensure all tasks are cleaned up
        await asyncio.gather(*tasks, return_exceptions=True)

    async def health_check_all(self) -> Dict[str, CrawlerHealth]:
        """Run health checks on all registered scrapers."""
        crawlers = self._get_crawlers()
        results = {}
        for crawler in crawlers:
            try:
                health = await crawler.health_check()
                results[crawler.platform] = health
            except Exception as exc:
                results[crawler.platform] = CrawlerHealth(
                    healthy=False,
                    last_check=datetime.now(UTC),
                    avg_latency_ms=0,
                    success_rate=0,
                    last_error=str(exc),
                )
        return results
