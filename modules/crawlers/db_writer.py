from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.crawlers.result import CrawlerResult
from shared.data_quality import apply_quality_to_model
from shared.models import SocialProfile

logger = logging.getLogger(__name__)


async def upsert_social_profile(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID | None = None,
) -> SocialProfile:
    """
    Upsert a SocialProfile from a CrawlerResult.
    If handle+platform already exists, updates it. Otherwise inserts.
    """
    handle = result.data.get("handle") or result.identifier
    result.data.get("platform_user_id")

    # Try to find existing
    stmt = select(SocialProfile).where(
        SocialProfile.platform == result.platform,
        SocialProfile.handle == handle,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing:
        profile = existing
    else:
        profile = SocialProfile(platform=result.platform)
        session.add(profile)

    # Apply fields
    db_dict = result.to_db_dict()
    for key, value in db_dict.items():
        if hasattr(profile, key) and value is not None:
            setattr(profile, key, value)

    if person_id:
        profile.person_id = person_id

    # Apply quality scores
    apply_quality_to_model(
        profile,
        last_scraped_at=result.scraped_at,
        source_type="social_media_profile",
        source_name=result.platform,
        corroboration_count=1,
    )

    await session.flush()
    logger.info("Upserted SocialProfile: %s/%s", result.platform, handle)
    return profile
