"""
cyber_abuseipdb.py — AbuseIPDB IP reputation crawler.

Checks an IP address against the AbuseIPDB database for abuse reports.
Registered as "cyber_abuseipdb".
Requires ABUSEIPDB_API_KEY in settings.
"""

from __future__ import annotations

import logging

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from shared.config import settings

logger = logging.getLogger(__name__)

_ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/check"

_DATA_FIELDS = {
    "ipAddress",
    "abuseConfidenceScore",
    "countryCode",
    "usageType",
    "isp",
    "totalReports",
    "lastReportedAt",
}


def _extract_data(raw: dict) -> dict:
    """Pull only the fields we surface from the API data block."""
    inner = raw.get("data", {})
    return {k: inner.get(k) for k in _DATA_FIELDS}


@register("cyber_abuseipdb")
class CyberAbuseIPDBCrawler(CurlCrawler):
    """
    Queries AbuseIPDB for abuse reports against an IP address.

    Requires a valid ABUSEIPDB_API_KEY in settings.
    source_reliability is 0.85 — community-sourced but well-moderated.
    Does not require Tor.
    """

    platform = "cyber_abuseipdb"
    category = CrawlerCategory.CYBER
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key = getattr(settings, "abuseipdb_api_key", "")
        if not api_key:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no api key",
                source_reliability=self.source_reliability,
            )

        ip = identifier.strip()
        headers = {
            "Key": api_key,
            "Accept": "application/json",
            "User-Agent": "Lycan-OSINT/1.0",
        }
        params = {
            "ipAddress": ip,
            "maxAgeInDays": 90,
            "verbose": "",
        }

        response = await self.get(_ABUSEIPDB_URL, headers=headers, params=params)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 401:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_api_key",
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
            raw = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        data = _extract_data(raw)
        total_reports = data.get("totalReports") or 0

        return self._result(
            identifier,
            found=total_reports > 0,
            **data,
        )
