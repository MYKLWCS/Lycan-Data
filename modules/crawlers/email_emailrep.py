"""
email_emailrep.py — EmailRep.io reputation crawler.

Checks an email address against the emailrep.io reputation database.
Returns reputation score, suspicious flags, breach and profile data.
Registered as "email_emailrep".
"""

from __future__ import annotations

import logging

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_EMAILREP_BASE = "https://emailrep.io/{identifier}"
_EMAILREP_HEADERS = {"User-Agent": "LycanOSINT/1.0"}


@register("email_emailrep")
class EmailRepCrawler(CurlCrawler):
    """
    Queries emailrep.io for reputation, breach, and profile data on an email address.

    source_reliability is 0.85 — emailrep aggregates from multiple authoritative sources.
    No API key required for basic queries (rate-limited on free tier).
    """

    platform = "email_emailrep"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        email = identifier.strip().lower()
        url = _EMAILREP_BASE.format(identifier=email)

        response = await self.get(url, headers=_EMAILREP_HEADERS)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
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

        reputation = json_data.get("reputation", "none")
        suspicious = json_data.get("suspicious", False)
        references = json_data.get("references", 0)
        details = json_data.get("details", {})

        found = reputation != "none" or suspicious is True

        data = {
            "email": json_data.get("email", email),
            "reputation": reputation,
            "suspicious": suspicious,
            "references": references,
            "details": {
                "blacklisted": details.get("blacklisted"),
                "malicious_activity": details.get("malicious_activity"),
                "credentials_leaked": details.get("credentials_leaked"),
                "data_breach": details.get("data_breach"),
                "profiles": details.get("profiles", []),
                "spam": details.get("spam"),
                "deliverability": details.get("deliverability"),
                "days_since_domain_creation": details.get("days_since_domain_creation"),
                "last_seen": details.get("last_seen"),
            },
        }

        return self._result(identifier, found=found, **data)
