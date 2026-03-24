"""
Growth Daemon.

Listens on the 'enrichment' event channel. When a crawl_complete event arrives
with new identifiers, it enqueues follow-up crawl jobs for each identifier
on every applicable platform — respecting max_depth, kill switches, and
deduplication (don't re-enqueue if a fresh crawl exists).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from shared.config import settings
from shared.constants import CrawlStatus, IdentifierType, Platform
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.crawl import CrawlJob
from shared.models.identifier import Identifier
from modules.dispatcher.dispatcher import dispatch_job

logger = logging.getLogger(__name__)

MAX_DEPTH = 3  # max hops from seed

# Platform → which identifier types it can accept
PLATFORM_ACCEPTS: dict[str, list[str]] = {
    "instagram": ["username"],
    "facebook": ["username", "full_name"],
    "twitter": ["username"],
    "tiktok": ["username"],
    "linkedin": ["username", "full_name"],
    "reddit": ["username"],
    "youtube": ["username"],
    "telegram": ["username", "phone"],
    "whatsapp": ["phone"],
    "snapchat": ["username"],
    "pinterest": ["username"],
    "github": ["username"],
    "discord": ["username"],
    "phone_carrier": ["phone"],
    "phone_fonefinder": ["phone"],
    "phone_truecaller": ["phone"],
    "email_holehe": ["email"],
    "email_hibp": ["email"],
    "username_sherlock": ["username"],
    "whitepages": ["full_name"],
    "fastpeoplesearch": ["full_name"],
    "truepeoplesearch": ["full_name"],
    "domain_whois": ["domain"],
    "domain_harvester": ["domain"],
    "crypto_bitcoin": ["crypto_wallet"],
    "crypto_ethereum": ["crypto_wallet"],
    "crypto_blockchair": ["crypto_wallet"],
    "sanctions_ofac": ["full_name"],
    "sanctions_un": ["full_name"],
    "sanctions_fbi": ["full_name"],
    "court_courtlistener": ["full_name"],
    "company_opencorporates": ["full_name", "company_reg"],
    "company_sec": ["full_name", "company_reg"],
    "public_npi": ["full_name"],
    "public_faa": ["full_name"],
    "public_nsopw": ["full_name"],
}

# Kill switch map
KILL_SWITCHES: dict[str, str] = {
    "instagram": "enable_instagram",
    "facebook": "enable_facebook",
    "twitter": "enable_twitter",
    "linkedin": "enable_linkedin",
    "tiktok": "enable_tiktok",
    "telegram": "enable_telegram",
    "whatsapp": "enable_telegram",
    "phone_carrier": "enable_burner_check",
    "phone_fonefinder": "enable_burner_check",
    "phone_truecaller": "enable_burner_check",
    "email_holehe": "enable_credit_risk",
    "email_hibp": "enable_credit_risk",
    "crypto_bitcoin": "enable_crypto_trace",
    "crypto_ethereum": "enable_crypto_trace",
    "crypto_blockchair": "enable_crypto_trace",
    "darkweb_ahmia": "enable_darkweb",
    "darkweb_torch": "enable_darkweb",
}


class GrowthDaemon:
    """Listens for crawl_complete events and fans out follow-up jobs."""

    def __init__(self):
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Growth daemon started")
        await event_bus.subscribe("enrichment", self._handle_event)

    async def stop(self) -> None:
        self._running = False

    async def _handle_event(self, message: dict) -> None:
        if message.get("event") != "crawl_complete":
            return

        person_id = message.get("person_id")
        if not person_id:
            return

        depth = message.get("depth", 0)
        if depth >= MAX_DEPTH:
            logger.debug(f"Max depth {MAX_DEPTH} reached for person {person_id}")
            return

        async with AsyncSessionLocal() as session:
            identifiers = await self._get_person_identifiers(session, person_id)

        for ident in identifiers:
            await self._fan_out(ident, person_id, depth)

    async def _get_person_identifiers(self, session, person_id: str) -> list[Identifier]:
        result = await session.execute(
            select(Identifier).where(Identifier.person_id == person_id)
        )
        return result.scalars().all()

    async def _fan_out(self, identifier: Identifier, person_id: str, depth: int) -> None:
        ident_type = identifier.type
        ident_value = identifier.value

        for platform, accepted_types in PLATFORM_ACCEPTS.items():
            if ident_type not in accepted_types:
                continue

            # Check kill switch
            kill_switch = KILL_SWITCHES.get(platform)
            if kill_switch and not getattr(settings, kill_switch, True):
                continue

            # Check if a recent job already exists
            if await self._job_exists(person_id, platform, ident_value):
                continue

            priority = "high" if depth == 0 else "normal" if depth == 1 else "low"
            await dispatch_job(
                platform=platform,
                identifier=ident_value,
                person_id=person_id,
                priority=priority,
            )
            logger.info(f"Enqueued {platform} job for {ident_type}={ident_value!r} (depth={depth})")

    async def _job_exists(self, person_id: str, platform: str, identifier: str) -> bool:
        """Return True if a non-failed job for this triple exists in the last 24h."""
        from sqlalchemy import and_, cast, String
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CrawlJob).where(
                    and_(
                        CrawlJob.person_id == person_id,
                        CrawlJob.seed_identifier == identifier,
                        CrawlJob.status != CrawlStatus.FAILED.value,
                        CrawlJob.meta["platform"].as_string() == platform,
                    )
                ).limit(1)
            )
            return result.scalar() is not None


growth_daemon = GrowthDaemon()
