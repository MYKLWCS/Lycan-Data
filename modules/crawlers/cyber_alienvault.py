"""
cyber_alienvault.py — AlienVault OTX (Open Threat Exchange) crawler.

Auto-detects the indicator type (IPv4, file hash, or domain) from the identifier
and queries the OTX general indicator endpoint.

Registered as "cyber_alienvault".
Optional API key (settings.otx_api_key) — limited queries work without one.
"""
from __future__ import annotations
import logging
import re

from shared.config import settings
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_OTX_URL = "https://otx.alienvault.com/api/v1/indicators/{type}/{identifier}/general"

_IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")


def _detect_type(identifier: str) -> str:
    """Return OTX indicator type string for the given identifier."""
    if _IPV4_RE.match(identifier):
        return "IPv4"
    if _HASH_RE.match(identifier):
        return "file"
    return "domain"


def _trim_pulses(raw: dict) -> dict:
    """Limit pulse list to first 5 entries to keep payload manageable."""
    pulse_info = raw.get("pulse_info", {})
    if isinstance(pulse_info, dict):
        pulses = pulse_info.get("pulses", [])
        if isinstance(pulses, list):
            pulse_info = dict(pulse_info)
            pulse_info["pulses"] = pulses[:5]
            raw = dict(raw)
            raw["pulse_info"] = pulse_info
    return raw


@register("cyber_alienvault")
class CyberAlienVaultCrawler(HttpxCrawler):
    """
    Queries AlienVault OTX for threat intelligence on an IP, domain, or file hash.

    Indicator type is auto-detected from the identifier value.
    API key is optional — unauthenticated requests are rate-limited.
    source_reliability is 0.85.
    Does not require Tor.
    """

    platform = "cyber_alienvault"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        target = identifier.strip()
        indicator_type = _detect_type(target)

        url = _OTX_URL.format(type=indicator_type, identifier=target)

        headers: dict[str, str] = {"User-Agent": "Lycan-OSINT/1.0"}
        api_key = getattr(settings, "otx_api_key", "")
        if api_key:
            headers["X-OTX-API-KEY"] = api_key

        response = await self.get(url, headers=headers)

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

        if response.status_code == 404:
            # OTX returns 404 for indicators with no data at all
            return self._result(
                identifier,
                found=False,
                indicator_type=indicator_type,
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

        data = _trim_pulses(raw)

        pulse_info = data.get("pulse_info", {})
        pulse_count = pulse_info.get("count", 0) if isinstance(pulse_info, dict) else 0
        reputation = data.get("reputation", 0) or 0

        found = pulse_count > 0 or reputation != 0

        return self._result(
            identifier,
            found=found,
            indicator_type=indicator_type,
            **data,
        )
