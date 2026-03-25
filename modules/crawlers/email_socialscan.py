"""
email_socialscan.py — Socialscan async library wrapper.

Checks whether an email address or username is registered across
major social platforms using the socialscan Python library.
Registered as "email_socialscan".
"""

from __future__ import annotations

import logging

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)


@register("email_socialscan")
class SocialscanCrawler(BaseCrawler):
    """
    Uses the socialscan library to check email/username registration
    across 20+ social platforms (Twitter, Instagram, GitHub, etc.).

    Requires: pip install socialscan
    """

    platform = "email_socialscan"
    source_reliability = 0.60
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        try:
            from socialscan.util import Platforms, Query, QueryHandler  # type: ignore[import]
        except ImportError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="socialscan_not_installed",
                source_reliability=self.source_reliability,
            )

        query = identifier.strip()
        try:
            platforms = list(Platforms)
            queries = [Query(query, p) for p in platforms]
            results = await QueryHandler().run(queries)
        except Exception as exc:
            logger.warning("socialscan failed for %s: %s", identifier, exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        registered_on = []
        available_on = []
        for res in results:
            platform_name = (
                res.platform.value if hasattr(res.platform, "value") else str(res.platform)
            )
            if res.available is False:
                # available=False means the account IS taken (registered)
                registered_on.append(platform_name)
            elif res.available is True:
                available_on.append(platform_name)

        return self._result(
            identifier,
            found=bool(registered_on),
            query=query,
            registered_on=registered_on,
            available_on=available_on,
            checked_count=len(results),
        )
