"""
interests_extractor.py — Interests Extractor meta-crawler.

Reads completed CrawlJob rows for a person from the DB, extracts interest
signals from Reddit subreddit membership, social bios, followed topics, and
liked-page signals. Writes deduplicated interests to BehaviouralProfile.interests.

Registered as "interests_extractor".
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# Keywords to extract interest signals from bio text
_BIO_INTEREST_KEYWORDS = [
    "crypto",
    "defi",
    "nft",
    "bitcoin",
    "ethereum",
    "fitness",
    "gym",
    "crossfit",
    "running",
    "cycling",
    "gaming",
    "esports",
    "twitch",
    "streaming",
    "music",
    "photography",
    "travel",
    "cooking",
    "coding",
    "investing",
    "stocks",
    "options",
    "trading",
    "real estate",
    "entrepreneur",
    "startup",
    "politics",
    "activism",
    "sustainability",
]


@register("interests_extractor")
class InterestsExtractorCrawler(BaseCrawler):
    """
    Meta-crawler: reads completed CrawlJob rows for a person from the DB,
    extracts interest signals from Reddit subreddit membership, social bios,
    and liked-page signals. Writes deduplicated interests to
    BehaviouralProfile.interests (ARRAY).

    identifier: person UUID string
    Requires 'session' kwarg (AsyncSession).
    """

    platform = "interests_extractor"
    SOURCE_RELIABILITY = 0.70
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str, **kwargs: Any) -> CrawlerResult:
        session = kwargs.get("session")
        if not session:
            logger.warning("InterestsExtractorCrawler requires a 'session' kwarg")
            return self._result(identifier, found=False, error="no_session")

        try:
            person_id: Any = uuid.UUID(identifier) if isinstance(identifier, str) else identifier
        except ValueError:
            # Non-UUID identifier — pass raw string; DB query will fail gracefully if invalid
            person_id = identifier

        from sqlalchemy import select

        from shared.models.crawl import CrawlJob

        result = await session.execute(
            select(CrawlJob).where(
                CrawlJob.person_id == person_id,
                CrawlJob.status == "done",
            )
        )
        jobs = result.scalars().all()

        if not jobs:
            return self._result(identifier, found=False)

        interests: list[str] = []

        for job in jobs:
            meta = job.meta or {}
            platform = meta.get("platform", "")
            job_result = meta.get("result") or {}

            # Reddit: extract subreddit memberships from recent posts
            if platform == "reddit":
                for post in job_result.get("recent_posts") or []:
                    sub = post.get("subreddit")
                    if sub and sub not in interests:
                        interests.append(sub.lower())

            # Social platforms: extract keywords from bio
            bio = job_result.get("bio") or job_result.get("description") or ""
            if bio:
                bio_lower = bio.lower()
                for keyword in _BIO_INTEREST_KEYWORDS:
                    if keyword in bio_lower and keyword not in interests:
                        interests.append(keyword)

            # Threads/Instagram: followed topics if available
            for topic in job_result.get("followed_topics") or []:
                t = topic.lower().strip()
                if t and t not in interests:
                    interests.append(t)

            # Liked pages signals (Facebook etc.)
            for page in job_result.get("liked_pages") or []:
                p = page.lower().strip() if isinstance(page, str) else ""
                if p and p not in interests:
                    interests.append(p)

        if not interests:
            return self._result(identifier, found=False)

        # Write to BehaviouralProfile.interests
        await self._persist_interests(person_id, interests, session)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"interests": interests, "count": len(interests)},
            source_reliability=self.SOURCE_RELIABILITY,
        )

    async def _persist_interests(
        self, person_id: uuid.UUID, interests: list[str], session: Any
    ) -> None:
        """Upsert interests into BehaviouralProfile.interests ARRAY."""
        from sqlalchemy import select

        from shared.models.behavioural import BehaviouralProfile

        result = await session.execute(
            select(BehaviouralProfile).where(BehaviouralProfile.person_id == person_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            profile = BehaviouralProfile(person_id=person_id, interests=interests)
            session.add(profile)
        else:
            # Merge existing + new, deduplicate, preserve order
            existing = list(profile.interests or [])
            merged = existing + [i for i in interests if i not in existing]
            profile.interests = merged

        try:
            await session.flush()
            await session.commit()
        except Exception as exc:
            logger.warning("InterestsExtractor persist failed: %s", exc)
            try:
                await session.rollback()
            except Exception:
                pass
