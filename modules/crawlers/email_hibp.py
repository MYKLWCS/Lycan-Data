"""
email_hibp.py — Have I Been Pwned (HIBP) free API crawler.

Uses the HIBP v2 public API to check if an email address appears in known data breaches.
Registered as "email_hibp".
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

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
class EmailHIBPCrawler(HttpxCrawler):
    """
    Checks an email address against the Have I Been Pwned breach database.

    Uses the v2 public endpoint — no API key required.
    source_reliability is high (0.80) because HIBP is an authoritative breach index.
    """

    platform = "email_hibp"
    source_reliability = 0.80
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        email = identifier.strip().lower()
        url = _HIBP_BASE.format(email=email)

        response = await self.get(url, headers=_HIBP_HEADERS)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 404:
            # 404 means the email was not found in any breach — clean result
            return self._result(
                identifier,
                found=True,
                email=email,
                breaches=[],
                breach_count=0,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        breaches = _parse_breaches(json_data)

        return self._result(
            identifier,
            found=True,
            email=email,
            breaches=breaches,
            breach_count=len(breaches),
        )
