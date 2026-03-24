"""
news_archive.py — Internet Archive Wayback Machine snapshot crawler.

Checks availability of the closest snapshot around 2024-01-01, fetches the
10 most recent CDX index records, and queries the CDX count endpoint for the
total number of snapshots on record.

Registered as "news_archive".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_WAYBACK_AVAILABLE = "https://archive.org/wayback/available?url={url}&timestamp=20240101"
_CDX_RECORDS = (
    "https://web.archive.org/cdx/search/cdx"
    "?url={url}&output=json&limit=10&fl=timestamp,original,statuscode,length"
    "&from=20200101&collapse=timestamp:8"
)
_CDX_COUNT = (
    "https://web.archive.org/cdx/search/cdx"
    "?url={url}&output=json&limit=1&fl=timestamp&showNumPages=true"
)


def _parse_closest(data: dict) -> dict[str, Any]:
    """Extract the closest snapshot details from the availability response."""
    archived = data.get("archived_snapshots", {}).get("closest", {})
    if not archived:
        return {}
    return {
        "url": archived.get("url", ""),
        "timestamp": archived.get("timestamp", ""),
        "status": archived.get("status", ""),
        "available": archived.get("available", False),
    }


def _parse_cdx_records(rows: list[list]) -> list[dict[str, Any]]:
    """
    CDX JSON output: first row is the header, subsequent rows are records.
    Fields requested: timestamp, original, statuscode, length
    """
    records: list[dict[str, Any]] = []
    if not rows:
        return records
    header = rows[0]
    for row in rows[1:]:
        if len(row) < len(header):
            continue
        record: dict[str, Any] = {}
        for i, field in enumerate(header):
            record[field] = row[i]
        records.append(record)
    return records


@register("news_archive")
class NewsArchiveCrawler(HttpxCrawler):
    """
    Queries the Wayback Machine for archived snapshots of a URL or domain.

    identifier: URL (https://example.com/path) or domain (example.com)

    Data keys returned:
        closest_snapshot  — {url, timestamp, status, available}
        cdx_records       — last 10 snapshots {timestamp, original, statuscode, length}
        total_snapshots   — integer count of all archived records
    """

    platform = "news_archive"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        raw = identifier.strip()
        encoded = quote_plus(raw)

        closest_snapshot = await self._get_closest(raw)
        cdx_records = await self._get_cdx_records(encoded)
        total_snapshots = await self._get_cdx_count(encoded)

        found = bool(closest_snapshot.get("available")) or len(cdx_records) > 0

        return self._result(
            identifier,
            found=found,
            closest_snapshot=closest_snapshot,
            cdx_records=cdx_records,
            total_snapshots=total_snapshots,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_closest(self, url: str) -> dict[str, Any]:
        api_url = _WAYBACK_AVAILABLE.format(url=quote_plus(url))
        resp = await self.get(api_url)

        if resp is None or resp.status_code != 200:
            logger.debug(
                "Wayback available check failed (status=%s)",
                resp.status_code if resp else "None",
            )
            return {}

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Wayback available JSON parse error: %s", exc)
            return {}

        return _parse_closest(data)

    async def _get_cdx_records(self, encoded_url: str) -> list[dict[str, Any]]:
        api_url = _CDX_RECORDS.format(url=encoded_url)
        resp = await self.get(api_url)

        if resp is None or resp.status_code != 200:
            return []

        try:
            rows = resp.json()
        except Exception as exc:
            logger.warning("CDX records JSON parse error: %s", exc)
            return []

        if not isinstance(rows, list):
            return []

        return _parse_cdx_records(rows)

    async def _get_cdx_count(self, encoded_url: str) -> int:
        api_url = _CDX_COUNT.format(url=encoded_url)
        resp = await self.get(api_url)

        if resp is None or resp.status_code != 200:
            return 0

        try:
            # showNumPages returns a plain integer as JSON
            data = resp.json()
            if isinstance(data, int):
                return data
            # Sometimes returned as list with single int element
            if isinstance(data, list) and data:
                return int(data[0]) if str(data[0]).isdigit() else 0
        except Exception as exc:
            logger.warning("CDX count parse error: %s", exc)

        return 0
