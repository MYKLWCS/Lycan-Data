"""
Freshness Scheduler.

Runs every N minutes. Queries social_profiles for stale records based on
per-source-type SLA intervals and enqueues re-scrape jobs.

SLA intervals per spec:
  Social media: every 7 days
  People search: every 30 days
  Public records: every 90 days
  Dark web: every 14 days
  Corporate filings: every 30 days
"""

import asyncio
import logging
from datetime import timezone, datetime, timedelta

from sqlalchemy import select

from modules.dispatcher.dispatcher import dispatch_job
from shared.config import settings
from shared.db import AsyncSessionLocal
from shared.models.quality import FreshnessQueue
from shared.models.social_profile import SocialProfile

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 300  # scan every 5 minutes
BATCH_SIZE = 100  # process 100 stale records per scan

# SLA re-crawl intervals by source category (in days)
SOURCE_SLA_DAYS: dict[str, int] = {
    # Social media platforms — every 7 days
    "instagram": 7,
    "twitter": 7,
    "facebook": 7,
    "linkedin": 7,
    "tiktok": 7,
    "telegram": 7,
    "snapchat": 7,
    "reddit": 7,
    "youtube": 7,
    "github": 7,
    "discord": 7,
    "pinterest": 7,
    "whatsapp": 7,
    "mastodon": 7,
    "twitch": 7,
    "steam": 7,
    "onlyfans": 7,
    # People search — every 30 days
    "truecaller": 30,
    "whitepages": 30,
    "fastpeoplesearch": 30,
    "truepeoplesearch": 30,
    "people": 30,
    "phone": 30,
    "email": 30,
    "username": 30,
    # Public records — every 90 days
    "government_registry": 90,
    "court_record": 90,
    "court": 90,
    "property_registry": 90,
    "property": 90,
    "company_registry": 90,
    "company": 90,
    "financial_record": 90,
    "gov": 90,
    "sanctions": 90,
    "watchlist": 90,
    "bankruptcy": 90,
    # Dark web — every 14 days
    "dark_forum": 14,
    "dark_paste": 14,
    "dark_market": 14,
    "darkweb": 14,
    "paste_site": 14,
    "paste": 14,
    # Corporate filings — every 30 days
    "crypto": 30,
    "cyber": 30,
    "domain": 30,
    "ip": 30,
    "news": 30,
    "obituary": 90,
}

DEFAULT_SLA_DAYS = 30  # fallback for unknown source types


def _get_sla_days(platform: str) -> int:
    """Get re-crawl SLA in days for a platform/source type."""
    return SOURCE_SLA_DAYS.get(platform.lower(), DEFAULT_SLA_DAYS)


class FreshnessScheduler:
    def __init__(self):
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Freshness scheduler started (source-type SLA aware)")
        while self._running:
            try:
                await self._scan_and_queue()
            except Exception as exc:
                logger.exception(f"Scheduler error: {exc}")
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False

    async def _scan_and_queue(self) -> None:
        """Scan for stale records and enqueue re-scrape jobs based on per-source SLA."""
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
        """Find SocialProfile records that have exceeded their source-type SLA."""
        now = datetime.now(timezone.utc)
        # Get all profiles that have been scraped and check each against its SLA
        # We use the most aggressive SLA (7 days) as a DB filter, then check per-platform
        min_sla_cutoff = now - timedelta(days=7)

        result = await session.execute(
            select(SocialProfile)
            .where(SocialProfile.last_scraped_at.isnot(None))
            .where(SocialProfile.last_scraped_at < min_sla_cutoff)
            .order_by(SocialProfile.last_scraped_at.asc())
            .limit(BATCH_SIZE * 3)  # fetch more, filter in-memory by SLA
        )
        candidates = result.scalars().all()

        # Filter to only profiles that have exceeded their specific SLA
        stale: list[SocialProfile] = []
        for profile in candidates:
            sla_days = _get_sla_days(profile.platform or "unknown")
            cutoff = now - timedelta(days=sla_days)
            if profile.last_scraped_at and profile.last_scraped_at < cutoff:
                stale.append(profile)
                if len(stale) >= BATCH_SIZE:
                    break

        return stale

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
            scheduled_at=datetime.now(timezone.utc),
        )
        session.add(fq)

        # Dispatch low-priority crawl job
        from modules.crawlers.registry import get_crawler
        if settings.rescrape_on_staleness and profile.handle:
            if not get_crawler(profile.platform):
                return True  # Queued in freshness table but skip unregistered crawler
            await dispatch_job(
                platform=profile.platform,
                identifier=profile.handle,
                person_id=str(profile.person_id) if profile.person_id else None,
                priority="low",
            )

        return True


freshness_scheduler = FreshnessScheduler()
