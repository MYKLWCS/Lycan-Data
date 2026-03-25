"""
cyber_wayback.py — Wayback Machine (Internet Archive) crawler.

Two-step approach:
  1. Availability API — check for the closest snapshot to the current time.
  2. CDX API — fetch up to 10 recent snapshots with timestamp, URL, and status code.

Registered as "cyber_wayback".
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_AVAILABILITY_URL = "https://archive.org/wayback/available?url={identifier}"
_CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url={identifier}&output=json&limit=10&fl=timestamp,original,statuscode"
)
_HEADERS = {"User-Agent": "Lycan-OSINT/1.0", "Accept": "application/json"}


def _parse_cdx(raw: list) -> list[dict]:
    """
    CDX returns a 2-D JSON array where the first row is field names.
    Convert to list of dicts, skip the header row.
    """
    if not raw or len(raw) < 2:
        return []
    keys = raw[0]  # ["timestamp", "original", "statuscode"]
    out = []
    for row in raw[1:]:
        if isinstance(row, list) and len(row) == len(keys):
            out.append(dict(zip(keys, row, strict=False)))
    return out


@register("cyber_wayback")
class CyberWaybackCrawler(HttpxCrawler):
    """
    Queries the Internet Archive Wayback Machine for snapshot history.

    Step 1 fetches the closest available snapshot via the availability endpoint.
    Step 2 fetches up to 10 recent CDX index entries.

    source_reliability is 0.85.
    Does not require Tor.
    """

    platform = "cyber_wayback"
    category = CrawlerCategory.CYBER
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        target = identifier.strip()

        # Step 1 — availability check
        avail_url = _AVAILABILITY_URL.format(identifier=target)
        avail_response = await self.get(avail_url, headers=_HEADERS)

        closest_snapshot: dict | None = None

        if avail_response is not None and avail_response.status_code == 200:
            try:
                avail_data = avail_response.json()
                archived_snapshots = avail_data.get("archived_snapshots", {})
                closest = archived_snapshots.get("closest")
                if closest and closest.get("available"):
                    closest_snapshot = {
                        "url": closest.get("url"),
                        "timestamp": closest.get("timestamp"),
                        "status": closest.get("status"),
                    }
            except Exception:
                logger.warning("cyber_wayback: failed to parse availability response")

        # Step 2 — CDX snapshot history
        cdx_url = _CDX_URL.format(identifier=target)
        cdx_response = await self.get(cdx_url, headers=_HEADERS)

        recent_snapshots: list[dict] = []

        if cdx_response is not None and cdx_response.status_code == 200:
            try:
                cdx_raw = cdx_response.json()
                if isinstance(cdx_raw, list):
                    recent_snapshots = _parse_cdx(cdx_raw)
            except Exception:
                logger.warning("cyber_wayback: failed to parse CDX response")

        # If both requests failed entirely, treat as http_error
        if avail_response is None and cdx_response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=closest_snapshot is not None,
            closest_snapshot=closest_snapshot,
            recent_snapshots=recent_snapshots[:10],
            url=target,
        )
