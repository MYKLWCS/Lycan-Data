"""
gravatar.py — Gravatar profile lookup from email hash.

Free API, no key needed. Returns profile photo + basic bio.
"""

from __future__ import annotations

import hashlib
import logging

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)


@register("gravatar")
class GravatarCrawler(HttpxCrawler):
    """Look up Gravatar profile by email MD5 hash."""

    platform = "gravatar"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.6
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        email = identifier.strip().lower()
        if "@" not in email:
            return self._result(identifier, found=False)

        email_hash = hashlib.md5(email.encode()).hexdigest()
        profile_url = f"https://en.gravatar.com/{email_hash}.json"

        resp = await self.get(profile_url)
        if not resp or resp.status_code == 404:
            return self._result(identifier, found=False)
        if resp.status_code != 200:
            return self._result(identifier, found=False, error=f"http_{resp.status_code}")

        try:
            data = resp.json()
            entry = data.get("entry", [{}])[0]
        except Exception:
            return self._result(identifier, found=False, error="parse_error")

        display_name = entry.get("displayName") or entry.get("preferredUsername") or ""
        photo_url = entry.get("thumbnailUrl") or entry.get("photos", [{}])[0].get("value", "")
        bio = entry.get("aboutMe") or ""
        location = entry.get("currentLocation") or ""

        # Extract URLs from profile
        urls = []
        for url_entry in entry.get("urls", []):
            urls.append({"title": url_entry.get("title", ""), "url": url_entry.get("value", "")})

        # Extract accounts (linked social profiles)
        accounts = []
        for acct in entry.get("accounts", []):
            accounts.append(
                {
                    "domain": acct.get("domain", ""),
                    "display": acct.get("display", ""),
                    "url": acct.get("url", ""),
                    "username": acct.get("username", ""),
                }
            )

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={
                "email": email,
                "display_name": display_name,
                "bio": bio,
                "location": location,
                "profile_image_url": photo_url,
                "urls": urls,
                "accounts": accounts,
                "hash": email_hash,
            },
            profile_url=f"https://gravatar.com/{email_hash}",
            source_reliability=self.source_reliability,
        )
