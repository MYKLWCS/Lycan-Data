"""
Social posts analyzer — meta-enricher that post-processes already-scraped
social profile and post text. Runs biographical and psychological analysis
on cached text without hitting any external network endpoints.
"""

from __future__ import annotations

import logging

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("social_posts_analyzer")
class SocialPostsAnalyzerCrawler(BaseCrawler):
    """
    Takes scraped posts/bio text and runs biographical + psychological analysis.

    identifier formats:
      - "text:<raw_text>"  — analyze the supplied raw text directly
      - "<person_id>"      — in production, fetches SocialProfile from DB;
                             in the pure-function path the UUID string is used as text
    """

    platform = "social_posts_analyzer"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.65
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        texts: list[str] = []

        if identifier.startswith("text:"):
            texts = [identifier[5:]]
        else:
            # Would fetch from DB in production; return placeholder for pure function path
            texts = [identifier]

        from modules.enrichers.biographical import build_biographical_profile
        from modules.enrichers.psychological import build_psychological_profile

        bio_profile = build_biographical_profile(texts)
        psych_profile = build_psychological_profile(texts)

        return self._result(
            identifier=identifier,
            found=True,
            # DOB / biographical
            dob=bio_profile.dob.isoformat() if bio_profile.dob else None,
            dob_confidence=bio_profile.dob_confidence,
            marital_status=bio_profile.marital_status,
            children_count=bio_profile.children_count,
            parent_father_deceased=bio_profile.parent_father_deceased,
            parent_mother_deceased=bio_profile.parent_mother_deceased,
            # OCEAN / psychological
            ocean_openness=psych_profile.openness,
            ocean_conscientiousness=psych_profile.conscientiousness,
            ocean_extraversion=psych_profile.extraversion,
            ocean_agreeableness=psych_profile.agreeableness,
            ocean_neuroticism=psych_profile.neuroticism,
            emotional_triggers=psych_profile.emotional_triggers,
            dominant_themes=psych_profile.dominant_themes,
            product_predispositions=psych_profile.product_predispositions,
            financial_stress_language=psych_profile.financial_stress_language,
            gambling_language=psych_profile.gambling_language,
            psych_confidence=psych_profile.confidence,
        )
