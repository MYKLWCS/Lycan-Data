"""
email_dehashed.py — DeHashed breach database API crawler.

Searches the DeHashed database for an email, username, IP, domain,
name, or password hash across billions of leaked records.
Registered as "email_dehashed".
"""

from __future__ import annotations

import base64
import logging
import os

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_API_URL = "https://api.dehashed.com/search"


def _make_auth_header(email: str, api_key: str) -> str:
    credentials = f"{email}:{api_key}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


@register("email_dehashed")
class DeHashedCrawler(CurlCrawler):
    """
    Queries the DeHashed breach database API.

    Returns leaked records matching an email, username, name, IP, or domain.
    Requires DEHASHED_EMAIL and DEHASHED_API_KEY environment variables.
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
        creds = self._credentials()
        if not creds:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="DEHASHED_EMAIL or DEHASHED_API_KEY not set",
                source_reliability=self.source_reliability,
            )

        email, api_key = creds
        auth_header = _make_auth_header(email, api_key)
        headers = {
            "Accept": "application/json",
            "Authorization": auth_header,
            "User-Agent": "Lycan-OSINT/1.0",
        }

        query = identifier.strip()
        url = f"{_API_URL}?query={query}&size=100&page=1"

        try:
            response = await self.get(url, headers=headers)
        except Exception as exc:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_response",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 401:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_credentials",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 400:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="bad_request",
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
            data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        entries = data.get("entries", []) or []
        records = []
        for entry in entries:
            records.append(
                {
                    "id": entry.get("id"),
                    "email": entry.get("email"),
                    "username": entry.get("username"),
                    "name": entry.get("name"),
                    "ip_address": entry.get("ip_address"),
                    "phone": entry.get("phone"),
                    "database_name": entry.get("database_name"),
                    "hashed_password": entry.get("hashed_password"),
                }
            )

        return self._result(
            identifier,
            found=bool(records),
            query=query,
            records=records,
            total=data.get("total", len(records)),
            took=data.get("took"),
        )
