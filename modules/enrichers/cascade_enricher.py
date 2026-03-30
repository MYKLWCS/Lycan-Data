"""
cascade_enricher.py — Cross-seed cascade enricher.

When crawl results surface new identifiers for a person (e.g. an email found
inside a social profile's profile_data, or a phone linked from a breach record),
this enricher discovers those new seeds and automatically queues new CrawlJobs
for all applicable platforms — without duplicating work already in progress.

Seed sources scanned:
  - SocialProfile.profile_data   (email, phone, username, handle, linked_url)
  - SocialProfile.handle          (new username not yet in Identifier table)

For each new seed found, an Identifier row is created (upserted) and crawl
jobs dispatched for every platform in SEED_PLATFORM_MAP[seed_type].
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.search import SEED_PLATFORM_MAP
from modules.dispatcher.dispatcher import dispatch_job
from shared.constants import SeedType
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.models.social_profile import SocialProfile

logger = logging.getLogger(__name__)

# Fields inside profile_data JSONB that may contain pivotable seeds
_EMAIL_KEYS = ("email", "email_address", "contact_email")
_PHONE_KEYS = ("phone", "phone_number", "mobile", "contact_phone")
_USERNAME_KEYS = ("username", "handle", "screen_name", "login", "nickname")
_INSTAGRAM_KEYS = ("instagram", "instagram_handle", "instagram_username")
_TWITTER_KEYS = ("twitter", "twitter_handle", "twitter_username", "x_handle")
_LINKEDIN_KEYS = ("linkedin", "linkedin_url", "linkedin_profile")

# Regex helpers (mirrors search.py _auto_detect_type)
_RE_EMAIL = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_RE_PHONE = re.compile(r"^\+?\d[\d\s\-().]{7,15}$")


class CascadeEnricher:
    """
    Discovers new seeds from already-crawled profile data and queues new
    CrawlJobs for those seeds — creating Identifier rows where needed.
    """

    async def enrich(self, person_id: str, session: AsyncSession) -> int:
        """
        Run the cascade enricher for one person.

        Returns the number of newly queued jobs.
        """
        pid_uuid = uuid.UUID(person_id)

        # ── 1. Load existing identifiers so we don't re-queue ─────────────────
        existing_result = await session.execute(
            select(Identifier).where(Identifier.person_id == pid_uuid)
        )
        existing_ids: list[Identifier] = list(existing_result.scalars().all())
        known: set[tuple[str, str]] = {(i.type, i.normalized_value) for i in existing_ids}

        # ── 2. Load social profiles to mine profile_data ──────────────────────
        sp_result = await session.execute(
            select(SocialProfile).where(SocialProfile.person_id == pid_uuid)
        )
        profiles: list[SocialProfile] = list(sp_result.scalars().all())

        new_seeds: list[tuple[SeedType, str]] = []

        for profile in profiles:
            # Mine structured handle field on the profile row
            if profile.handle:
                new_seeds.extend(self._check_seed(SeedType.USERNAME, profile.handle.strip(), known))

            data: dict = profile.profile_data or {}

            # Email fields
            for key in _EMAIL_KEYS:
                val = data.get(key)
                if val and isinstance(val, str):
                    new_seeds.extend(self._check_seed(SeedType.EMAIL, val.strip(), known))

            # Phone fields
            for key in _PHONE_KEYS:
                val = data.get(key)
                if val and isinstance(val, str):
                    new_seeds.extend(self._check_seed(SeedType.PHONE, val.strip(), known))

            # Generic username fields
            for key in _USERNAME_KEYS:
                val = data.get(key)
                if val and isinstance(val, str):
                    new_seeds.extend(self._check_seed(SeedType.USERNAME, val.strip(), known))

            # Platform-specific pivot handles
            for key in _INSTAGRAM_KEYS:
                val = data.get(key)
                if val and isinstance(val, str):
                    new_seeds.extend(
                        self._check_seed(SeedType.INSTAGRAM_HANDLE, val.strip(), known)
                    )

            for key in _TWITTER_KEYS:
                val = data.get(key)
                if val and isinstance(val, str):
                    new_seeds.extend(self._check_seed(SeedType.TWITTER_HANDLE, val.strip(), known))

            for key in _LINKEDIN_KEYS:
                val = data.get(key)
                if val and isinstance(val, str):
                    new_seeds.extend(self._check_seed(SeedType.LINKEDIN_URL, val.strip(), known))

        # ── 2b. Mine Identifier table for unsearched entries ──────────────
        for ident in existing_ids:
            if ident.already_searched:
                continue
            if ident.type in ("email", "phone", "username") and ident.normalized_value:
                seed_map = {"email": SeedType.EMAIL, "phone": SeedType.PHONE, "username": SeedType.USERNAME}
                st = seed_map.get(ident.type)
                if st:
                    new_seeds.extend(self._check_seed(st, ident.normalized_value, known))
                    ident.already_searched = True

        if not new_seeds:
            return 0

        # ── 3. Create Identifier rows + dispatch jobs ─────────────────────────
        jobs_queued = 0
        for seed_type, value in new_seeds:
            normalized = value.lower().strip()
            identifier = Identifier(
                person_id=pid_uuid,
                type=seed_type.value,
                value=value,
                normalized_value=normalized,
                confidence=0.7,
                meta={"source": "cascade_enricher"},
            )
            session.add(identifier)
            await session.flush()

            platforms = SEED_PLATFORM_MAP.get(seed_type, [])
            for platform in platforms:
                await dispatch_job(
                    platform=platform,
                    identifier=value,
                    person_id=person_id,
                    priority="low",
                )
                jobs_queued += 1

            logger.info(
                "Cascade: person=%s new seed type=%s value=%r → %d jobs",
                person_id,
                seed_type.value,
                value,
                len(platforms),
            )

        # ── Cross-person collision detection ──
        # If we just stored an identifier that also exists on another person, flag for merge
        try:
            from modules.enrichers.deduplication import AsyncMergeExecutor
            for seed_type, value in new_seeds:
                collision_q = select(Identifier.person_id).where(
                    Identifier.normalized_value == value.lower().strip(),
                    Identifier.person_id != pid_uuid,
                )
                collisions = (await session.execute(collision_q)).scalars().all()
                for other_pid in collisions:
                    if other_pid and other_pid != pid_uuid:
                        # Auto-merge: keep the person with more data
                        p1_count = (await session.execute(
                            select(func.count()).select_from(Identifier).where(
                                Identifier.person_id == pid_uuid
                            )
                        )).scalar() or 0
                        p2_count = (await session.execute(
                            select(func.count()).select_from(Identifier).where(
                                Identifier.person_id == other_pid
                            )
                        )).scalar() or 0
                        canonical = pid_uuid if p1_count >= p2_count else other_pid
                        duplicate = other_pid if canonical == pid_uuid else pid_uuid

                        # Follow merged_into chain to find true canonical
                        for _ in range(10):  # max hops
                            canon_person = await session.get(Person, canonical)
                            if canon_person and canon_person.merged_into:
                                canonical = canon_person.merged_into
                            else:
                                break

                        dup_person = await session.get(Person, duplicate)
                        if dup_person and dup_person.merged_into:
                            for _ in range(10):
                                if dup_person.merged_into:
                                    duplicate = dup_person.merged_into
                                    dup_person = await session.get(Person, duplicate)
                                else:
                                    break

                        if canonical == duplicate:
                            continue  # Same person after chain resolution

                        merger = AsyncMergeExecutor()
                        await merger.execute(
                            {"canonical_id": str(canonical), "duplicate_id": str(duplicate)},
                            session,
                        )
                        logger.info(
                            "Cascade: merged person %s into %s (shared identifier %s=%s)",
                            duplicate, canonical, seed_type.value, value,
                        )
                        break  # Only merge once per enrichment cycle
        except Exception as exc:
            logger.debug("Cross-person collision check failed: %s", exc)

        return jobs_queued

    def _check_seed(
        self,
        seed_type: SeedType,
        value: str,
        known: set[tuple[str, str]],
    ) -> list[tuple[SeedType, str]]:
        """
        Return [(seed_type, value)] if this seed is valid and not already known,
        else [].  Also marks the seed as known to avoid duplicates within a run.
        """
        if not value:
            return []

        # Basic format validation
        if seed_type == SeedType.EMAIL and not _RE_EMAIL.match(value):
            return []
        if seed_type == SeedType.PHONE and not _RE_PHONE.match(value):
            return []

        normalized = value.lower().strip()
        key = (seed_type.value, normalized)
        if key in known:
            return []

        known.add(key)  # Mark as seen so the same value isn't queued twice
        return [(seed_type, value)]
