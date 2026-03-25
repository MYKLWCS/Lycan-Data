#!/usr/bin/env python
"""
Lycan Worker — background job processor.

Usage:
    python worker.py                    # 4 dispatcher workers (default)
    python worker.py --workers 8        # 8 concurrent workers
    python worker.py --no-growth        # disable growth daemon
    python worker.py --no-freshness     # disable freshness scheduler

This process handles:
  - Crawl job dispatch (pulls from Dragonfly queues)
  - Growth daemon (auto-enqueues follow-up jobs)
  - Freshness scheduler (detects and re-queues stale records)
"""

import argparse
import asyncio
import importlib
import logging
import pkgutil
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lycan.worker")


def _import_all_crawlers():
    import modules.crawlers as pkg

    for _finder, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        try:
            mod = importlib.import_module(f"modules.crawlers.{name}")
            if ispkg:
                import pkgutil as _pkgutil

                for _, subname, _ in _pkgutil.iter_modules(mod.__path__):
                    try:
                        importlib.import_module(f"modules.crawlers.{name}.{subname}")
                    except Exception:
                        pass
        except Exception:
            pass


async def main(
    workers: int,
    enable_growth: bool,
    enable_freshness: bool,
    enable_commercial: bool = True,
    enable_audit: bool = True,
    enable_genealogy: bool = True,
    enable_property: bool = True,
    enable_pep: bool = True,
    enable_adverse_media: bool = True,
):
    # Setup
    _import_all_crawlers()
    from modules.dispatcher.dispatcher import CrawlDispatcher
    from modules.dispatcher.freshness_scheduler import FreshnessScheduler
    from modules.dispatcher.growth_daemon import GrowthDaemon
    from modules.enrichers.auto_dedup import AutoDedupDaemon
    from modules.pipeline.ingestion_daemon import IngestionDaemon
    from modules.search.index_daemon import IndexDaemon
    from modules.search.meili_indexer import meili_indexer
    from shared.events import event_bus
    from shared.tor import tor_manager

    await event_bus.connect()
    await tor_manager.connect_all()
    await meili_indexer.setup_index()

    tor_status = tor_manager.status()
    active_tor = sum(1 for v in tor_status.values() if v)
    logger.info(f"Tor circuits: {active_tor}/3 active")

    tasks = []

    # Dispatcher workers (Crawlers)
    for i in range(workers):
        d = CrawlDispatcher(worker_id=f"dispatcher-{i + 1}")
        tasks.append(asyncio.create_task(d.start(), name=f"dispatcher-{i + 1}"))
        logger.info(f"Started dispatcher worker-{i + 1}")

    # Ingestion workers (Database writes)
    for i in range(2):  # 2 ingesters by default
        ingest = IngestionDaemon(worker_id=f"ingester-{i + 1}")
        tasks.append(asyncio.create_task(ingest.start(), name=f"ingester-{i + 1}"))
        logger.info(f"Started ingestion daemon-{i + 1}")

    # Index worker (MeiliSearch writes)
    indexer = IndexDaemon(worker_id="indexer-1")
    tasks.append(asyncio.create_task(indexer.start(), name="indexer-1"))
    logger.info("Started index daemon-1")

    # Growth daemon
    if enable_growth:
        gd = GrowthDaemon()
        tasks.append(asyncio.create_task(gd.start(), name="growth-daemon"))
        logger.info("Started growth daemon")

    # Freshness scheduler
    if enable_freshness:
        fs = FreshnessScheduler()
        tasks.append(asyncio.create_task(fs.start(), name="freshness-scheduler"))
        logger.info("Started freshness scheduler")

    # Auto-dedup daemon
    dedup_daemon = AutoDedupDaemon()
    tasks.append(asyncio.create_task(dedup_daemon.start(), name="auto-dedup-daemon"))
    logger.info("Started auto-dedup daemon")

    # Commercial tagger daemon
    if enable_commercial:
        from modules.enrichers.commercial_tagger import CommercialTaggerDaemon

        ct = CommercialTaggerDaemon()
        tasks.append(asyncio.create_task(ct.start(), name="commercial-tagger"))
        logger.info("Started commercial tagger daemon")

    # Audit daemon (hourly platform health snapshots)
    if enable_audit:
        from modules.audit.audit_daemon import AuditDaemon

        ad = AuditDaemon()
        tasks.append(asyncio.create_task(ad.start(), name="audit-daemon"))
        logger.info("Started audit daemon")

    # Genealogy enricher daemon
    if enable_genealogy:
        from modules.enrichers.genealogy_enricher import GenealogyEnricher

        ge = GenealogyEnricher()
        tasks.append(asyncio.create_task(ge.start(), name="genealogy-enricher"))
        logger.info("Started genealogy enricher daemon")

    # Property enricher (properties, aircraft, vessels, net worth)
    if enable_property:
        from modules.enrichers.property_enricher import PropertyEnricher

        pe = PropertyEnricher()
        tasks.append(asyncio.create_task(pe.start(), name="property-enricher"))
        logger.info("Started property enricher daemon")

    # PEP classifier daemon
    if enable_pep:
        from modules.enrichers.pep_enricher import PepEnricher

        pep = PepEnricher()
        tasks.append(asyncio.create_task(pep.start(), name="pep-enricher"))
        logger.info("Started PEP enricher daemon")

    # Adverse media monitor
    if enable_adverse_media:
        from modules.enrichers.adverse_media_enricher import AdverseMediaEnricher

        ame = AdverseMediaEnricher()
        tasks.append(asyncio.create_task(ame.start(), name="adverse-media-enricher"))
        logger.info("Started adverse media enricher daemon")

    logger.info(
        f"Worker running — {workers} dispatcher(s) + "
        f"{'growth + ' if enable_growth else ''}"
        f"{'freshness + ' if enable_freshness else ''}"
        f"{'commercial + ' if enable_commercial else ''}"
        f"{'audit + ' if enable_audit else ''}"
        f"{'genealogy + ' if enable_genealogy else ''}"
        f"{'property + ' if enable_property else ''}"
        f"{'pep + ' if enable_pep else ''}"
        f"{'adverse-media + ' if enable_adverse_media else ''}"
        f"auto-dedup"
    )

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown():
        logger.info("Shutdown signal received — stopping workers...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await event_bus.disconnect()
    logger.info("Worker stopped cleanly.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lycan background worker")
    parser.add_argument("--workers", type=int, default=4, help="Number of dispatcher workers")
    parser.add_argument("--no-growth", action="store_true", help="Disable growth daemon")
    parser.add_argument("--no-freshness", action="store_true", help="Disable freshness scheduler")
    parser.add_argument(
        "--no-commercial", action="store_true", help="Disable commercial tagger daemon"
    )
    parser.add_argument(
        "--no-genealogy", action="store_true", help="Disable genealogy enricher daemon"
    )
    parser.add_argument("--no-audit", action="store_true", help="Disable audit daemon")
    parser.add_argument("--no-property", action="store_true", help="Disable property enricher daemon")
    parser.add_argument("--no-pep", action="store_true", help="Disable PEP enricher daemon")
    parser.add_argument("--no-adverse-media", action="store_true", help="Disable adverse media daemon")
    args = parser.parse_args()

    asyncio.run(
        main(
            workers=args.workers,
            enable_growth=not args.no_growth,
            enable_freshness=not args.no_freshness,
            enable_commercial=not args.no_commercial,
            enable_audit=not args.no_audit,
            enable_genealogy=not args.no_genealogy,
            enable_property=not args.no_property,
            enable_pep=not args.no_pep,
            enable_adverse_media=not args.no_adverse_media,
        )
    )
