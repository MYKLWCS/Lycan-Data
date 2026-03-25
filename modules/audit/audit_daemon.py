"""AuditDaemon — hourly platform health snapshots written to system_audits."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from shared.db import AsyncSessionLocal
from shared.models.audit import SystemAudit
from shared.models.crawl import DataSource
from shared.models.person import Person

logger = logging.getLogger(__name__)

_SLEEP_SECONDS = 3600  # 1 hour


class AuditDaemon:
    """Background daemon: runs an audit every hour and persists a SystemAudit row."""

    def __init__(self) -> None:
        self._running = False

    def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("AuditDaemon started")
        while self._running:
            try:
                await self._run_audit()
            except Exception:
                logger.exception("AuditDaemon: unexpected error in run loop")
            await asyncio.sleep(_SLEEP_SECONDS)

    async def _run_audit(self) -> None:
        """Execute all four audit categories and persist a SystemAudit row."""
        logger.info("AuditDaemon: starting audit run")
        run_at = datetime.now(UTC)

        try:
            async with AsyncSessionLocal() as session:
                # ── 1. Per-person quality metrics ─────────────────────────────

                persons_total = (
                    await session.execute(
                        select(func.count(Person.id)).where(Person.merged_into.is_(None))
                    )
                ).scalar() or 0

                persons_low_coverage = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM persons "
                            "WHERE merged_into IS NULL "
                            "AND (meta->'coverage'->>'pct')::numeric < 50"
                        )
                    )
                ).scalar() or 0

                today_start = run_at.replace(hour=0, minute=0, second=0, microsecond=0)
                stale_cutoff = run_at - timedelta(days=30)

                persons_stale = (
                    await session.execute(
                        select(func.count(Person.id)).where(
                            Person.merged_into.is_(None),
                            Person.last_scraped_at < stale_cutoff,
                        )
                    )
                ).scalar() or 0

                persons_conflict = (
                    await session.execute(
                        select(func.count(Person.id)).where(
                            Person.merged_into.is_(None),
                            Person.conflict_flag.is_(True),
                        )
                    )
                ).scalar() or 0

                # ── 2. Crawler health (CrawlJob last 24h) ────────────────────

                crawlers_total = (
                    await session.execute(
                        select(func.count(DataSource.id)).where(DataSource.is_enabled.is_(True))
                    )
                ).scalar() or 0

                crawl_rows = (
                    (
                        await session.execute(
                            text(
                                "SELECT job_type, "
                                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS found_count, "
                                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS error_count "
                                "FROM crawl_jobs "
                                "WHERE created_at >= NOW() - INTERVAL '24 hours' "
                                "GROUP BY job_type"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )

                crawlers_degraded = []
                crawlers_healthy = 0

                for row in crawl_rows:
                    found = int(row["found_count"] or 0)
                    errors = int(row["error_count"] or 0)
                    total = found + errors
                    if total == 0:
                        # No activity — skip
                        continue
                    rate = found / total
                    if rate == 0.0:
                        crawlers_degraded.append(
                            {"name": row["job_type"], "success_rate": round(rate, 4)}
                        )
                    else:
                        crawlers_healthy += 1

                # ── 3. Data volume (today) ────────────────────────────────────

                tags_assigned_today = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM marketing_tags WHERE scored_at >= :today"),
                        {"today": today_start},
                    )
                ).scalar() or 0

                merges_today = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM audit_log "
                            "WHERE action = 'auto_merge' "
                            "AND access_time >= :today"
                        ),
                        {"today": today_start},
                    )
                ).scalar() or 0

                persons_ingested_today = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM persons WHERE created_at >= :today"),
                        {"today": today_start},
                    )
                ).scalar() or 0

                # ── 4. Persist ────────────────────────────────────────────────

                row_obj = SystemAudit(
                    run_at=run_at,
                    persons_total=int(persons_total),
                    persons_low_coverage=int(persons_low_coverage),
                    persons_stale=int(persons_stale),
                    persons_conflict=int(persons_conflict),
                    crawlers_total=int(crawlers_total),
                    crawlers_healthy=crawlers_healthy,
                    crawlers_degraded=crawlers_degraded,
                    tags_assigned_today=int(tags_assigned_today),
                    merges_today=int(merges_today),
                    persons_ingested_today=int(persons_ingested_today),
                    meta={},
                )
                session.add(row_obj)
                await session.commit()

                logger.info(
                    "AuditDaemon: audit complete — persons=%d low_cov=%d stale=%d "
                    "conflict=%d degraded_crawlers=%d",
                    persons_total,
                    persons_low_coverage,
                    persons_stale,
                    persons_conflict,
                    len(crawlers_degraded),
                )

        except Exception:
            logger.exception("AuditDaemon: _run_audit failed")
