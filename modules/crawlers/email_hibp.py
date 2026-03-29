"""
email_hibp.py — Have I Been Pwned (HIBP) API crawler.

DISABLED: HIBP v2 public API now requires a paid API key ($3.50/mo).
Use email_breach crawler instead (free, checks PSBDMP + GitHub + LeakCheck).

Registered as "email_hibp" but returns disabled error immediately.
"""

from __future__ import annotations

import logging

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_HIBP_BASE = "https://haveibeenpwned.com/api/v2/breachedaccount/{email}"
_HIBP_HEADERS = {"User-Agent": "Lycan-OSINT/1.0"}


def _parse_breaches(json_data: list[dict]) -> list[dict]:
    """Extract relevant fields from HIBP breach list."""
    out = []
    for item in json_data:
        out.append(
            {
                "name": item.get("Name", ""),
                "domain": item.get("Domain", ""),
                "date": item.get("BreachDate", ""),
                "data_classes": item.get("DataClasses", []),
            }
        )
    return out


@register("email_hibp")
class EmailHIBPCrawler(CurlCrawler):
    """
    Checks an email address against the Have I Been Pwned breach database.

    Uses the v2 public endpoint — no API key required.
    source_reliability is high (0.80) because HIBP is an authoritative breach index.
    """

    platform = "email_hibp"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.80
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        # DISABLED: HIBP v2 API requires paid key ($3.50/mo).
        # Use email_breach crawler instead (free alternative).
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=False,
            error="disabled: HIBP API requires paid key. Use email_breach crawler instead.",
            source_reliability=0.0,
        )
