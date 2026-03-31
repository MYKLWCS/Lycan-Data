"""
email_dehashed.py — legacy DeHashed compatibility crawler.

The free-only Lycan runtime keeps this platform registered for backwards
compatibility, but the live scrape path is disabled so the repo does not
depend on DeHashed's paid API.
"""

from __future__ import annotations

import base64
import logging
import os

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_API_URL = "https://api.dehashed.com/search"


def _make_auth_header(email: str, api_key: str) -> str:
    credentials = f"{email}:{api_key}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


@register("email_dehashed")
class DeHashedCrawler(CurlCrawler):
    """
    Legacy compatibility stub for the retired DeHashed paid crawler.
    """

    platform = "email_dehashed"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.75
    requires_tor = False

    def _credentials(self) -> tuple[str, str] | None:
        email = os.getenv("DEHASHED_EMAIL")
        api_key = os.getenv("DEHASHED_API_KEY")
        if email and api_key:
            return email, api_key
        return None

    async def scrape(self, identifier: str) -> CrawlerResult:
        if self._credentials():
            logger.info("Ignoring configured DeHashed credentials; paid crawler is disabled")

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=False,
            error="dehashed_disabled_free_only_runtime",
            source_reliability=self.source_reliability,
        )
