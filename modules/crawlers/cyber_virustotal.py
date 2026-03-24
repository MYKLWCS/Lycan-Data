"""
cyber_virustotal.py — VirusTotal threat intelligence crawler.

Auto-detects the identifier type:
  - IPv4 address  → /api/v3/ip_addresses/{ip}
  - URL (http/s)  → /api/v3/urls  (POST with base64url-encoded URL id)
  - Anything else → /api/v3/domains/{domain}

Returns malicious/suspicious vote counts, reputation score, categories, and
the full last_analysis_stats breakdown.

Registered as "cyber_virustotal".
Requires settings.virustotal_api_key.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any
from urllib.parse import quote

from shared.config import settings
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_VT_BASE = "https://www.virustotal.com/api/v3"

_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)


def _is_ipv4(value: str) -> bool:
    return bool(_IPV4_RE.match(value.strip()))


def _is_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def _vt_url_id(url: str) -> str:
    """VirusTotal URL identifier: base64url-encoded URL (no padding)."""
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return encoded


def _extract_attributes(data: dict) -> dict[str, Any]:
    """Pull unified threat fields from a VT /attributes block."""
    attrs = data.get("data", {}).get("attributes", {})
    stats = attrs.get("last_analysis_stats", {})
    return {
        "malicious": stats.get("malicious", 0),
        "suspicious": stats.get("suspicious", 0),
        "total_votes": attrs.get("total_votes", {}),
        "reputation": attrs.get("reputation", 0),
        "categories": attrs.get("categories", {}),
        "last_analysis_stats": stats,
    }


@register("cyber_virustotal")
class VirusTotalCrawler(HttpxCrawler):
    """
    Queries VirusTotal for domain, IP, or URL threat intelligence.

    identifier: domain name, IPv4 address, or full URL (http/https)

    Data keys returned:
        malicious, suspicious, total_votes, reputation,
        categories, last_analysis_stats
    """

    platform = "cyber_virustotal"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key: str = getattr(settings, "virustotal_api_key", "")
        if not api_key:
            return self._result(identifier, found=False, error="not_configured")

        query = identifier.strip()
        headers = {
            "x-apikey": api_key,
            "Accept": "application/json",
        }

        if _is_ipv4(query):
            return await self._query_ip(identifier, query, headers)
        if _is_url(query):
            return await self._query_url(identifier, query, headers)
        return await self._query_domain(identifier, query, headers)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _query_ip(
        self, identifier: str, ip: str, headers: dict
    ) -> CrawlerResult:
        url = f"{_VT_BASE}/ip_addresses/{ip}"
        resp = await self.get(url, headers=headers)
        return self._handle_response(identifier, resp, endpoint="ip")

    async def _query_domain(
        self, identifier: str, domain: str, headers: dict
    ) -> CrawlerResult:
        safe = quote(domain, safe="")
        url = f"{_VT_BASE}/domains/{safe}"
        resp = await self.get(url, headers=headers)
        return self._handle_response(identifier, resp, endpoint="domain")

    async def _query_url(
        self, identifier: str, raw_url: str, headers: dict
    ) -> CrawlerResult:
        url_id = _vt_url_id(raw_url)
        url = f"{_VT_BASE}/urls/{url_id}"
        resp = await self.get(url, headers=headers)
        return self._handle_response(identifier, resp, endpoint="url")

    def _handle_response(
        self, identifier: str, resp: Any, endpoint: str
    ) -> CrawlerResult:
        if resp is None:
            return self._result(identifier, found=False, error="http_error")

        if resp.status_code == 401:
            return self._result(identifier, found=False, error="invalid_api_key")

        if resp.status_code == 404:
            return self._result(
                identifier, found=False, error="not_found", endpoint=endpoint
            )

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited")

        if resp.status_code != 200:
            return self._result(
                identifier, found=False, error=f"http_{resp.status_code}"
            )

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("VirusTotal JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error")

        extracted = _extract_attributes(data)
        malicious = extracted.get("malicious", 0) or 0
        suspicious = extracted.get("suspicious", 0) or 0
        found = (malicious + suspicious) > 0

        return self._result(
            identifier, found=found, endpoint=endpoint, **extracted
        )
