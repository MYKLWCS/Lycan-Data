"""
people_phonebook.py — Phonebook.name OSINT scraper.

Searches phonebook.name for emails, URLs, and subdomains
associated with a full name or domain.
Registered as "people_phonebook".
"""

from __future__ import annotations

import logging
import re

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://phonebook.cz/ui/v1/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


@register("people_phonebook")
class PhonebookCrawler(CurlCrawler):
    """
    Scrapes phonebook.cz (Phonebook.name) for email addresses, URLs,
    and subdomain intelligence tied to a name or domain.

    Uses the public search API. No API key required.
    """

    platform = "people_phonebook"
    source_reliability = 0.55
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        payload = {
            "term": query,
            "maxResults": 100,
            "startWithDomain": False,
        }

        try:
            response = await self.post(_BASE_URL, json=payload, headers=_HEADERS)
        except Exception as exc:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "none"
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{status}",
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

        hits = data.get("hits", []) if isinstance(data, dict) else []
        emails = []
        urls = []
        subdomains = []

        email_re = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

        for item in hits:
            value = item.get("value", "") if isinstance(item, dict) else str(item)
            if "@" in value and email_re.match(value):
                emails.append(value.lower())
            elif value.startswith("http"):
                urls.append(value)
            else:
                subdomains.append(value)

        return self._result(
            identifier,
            found=bool(hits),
            query=query,
            emails=emails,
            urls=urls,
            subdomains=subdomains,
            total_hits=len(hits),
        )
