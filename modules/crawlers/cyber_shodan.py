"""
cyber_shodan.py — Shodan host intelligence and search crawler.

For IPv4 addresses, queries the Shodan host endpoint to retrieve open ports,
vulnerabilities, ISP, org, and geolocation. For search queries (domain names or
arbitrary terms), uses the Shodan host search endpoint with country and org facets.

Registered as "cyber_shodan".
Requires settings.shodan_api_key.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://api.shodan.io"
_HOST_URL = _BASE + "/shodan/host/{ip}?key={api_key}"
_SEARCH_URL = (
    _BASE + "/shodan/host/search?key={api_key}&query={query}&facets=country,org&minify=true"
)

_IPV4_RE = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$")


def _is_ipv4(value: str) -> bool:
    return bool(_IPV4_RE.match(value.strip()))


def _parse_host(data: dict) -> dict[str, Any]:
    """Extract relevant fields from a Shodan host response."""
    return {
        "open_ports": data.get("ports", []),
        "vulns": list(data.get("vulns", {}).keys())
        if isinstance(data.get("vulns"), dict)
        else data.get("vulns", []),
        "org": data.get("org", ""),
        "country": data.get("country_name", ""),
        "isp": data.get("isp", ""),
        "hostnames": data.get("hostnames", []),
        "last_update": data.get("last_update", ""),
    }


def _parse_search(data: dict) -> dict[str, Any]:
    """Extract relevant fields from a Shodan search response."""
    total = data.get("total", 0)
    matches: list[dict[str, Any]] = []
    for item in data.get("matches", []):
        matches.append(
            {
                "ip_str": item.get("ip_str", ""),
                "ports": item.get("ports", []),
                "org": item.get("org", ""),
                "country_code": item.get("location", {}).get("country_code", ""),
            }
        )
    return {"total": total, "matches": matches}


@register("cyber_shodan")
class ShodanCrawler(CurlCrawler):
    """
    Queries Shodan for host intelligence or search results.

    identifier: IPv4 address → host endpoint
                domain / query string → search endpoint

    Data keys returned (host mode):
        open_ports, vulns, org, country, isp, hostnames, last_update

    Data keys returned (search mode):
        total, matches (list of ip_str, ports, org, country_code)
    """

    platform = "cyber_shodan"
    category = CrawlerCategory.CYBER
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key: str = getattr(settings, "shodan_api_key", "")
        if not api_key:
            return self._result(
                identifier,
                found=False,
                error="not_configured",
            )

        query = identifier.strip()

        if _is_ipv4(query):
            return await self._scrape_host(identifier, query, api_key)
        return await self._scrape_search(identifier, query, api_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_host(self, identifier: str, ip: str, api_key: str) -> CrawlerResult:
        url = _HOST_URL.format(ip=ip, api_key=api_key)
        resp = await self.get(url)

        if resp is None:
            return self._result(identifier, found=False, error="http_error")

        if resp.status_code == 404:
            return self._result(identifier, found=False, error="not_found")

        if resp.status_code == 401:
            return self._result(identifier, found=False, error="invalid_api_key")

        if resp.status_code != 200:
            return self._result(identifier, found=False, error=f"http_{resp.status_code}")

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Shodan host JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error")

        parsed = _parse_host(data)
        return self._result(identifier, found=True, mode="host", **parsed)

    async def _scrape_search(self, identifier: str, query: str, api_key: str) -> CrawlerResult:
        encoded = quote_plus(query)
        url = _SEARCH_URL.format(api_key=api_key, query=encoded)
        resp = await self.get(url)

        if resp is None:
            return self._result(identifier, found=False, error="http_error")

        if resp.status_code == 401:
            return self._result(identifier, found=False, error="invalid_api_key")

        if resp.status_code != 200:
            return self._result(identifier, found=False, error=f"http_{resp.status_code}")

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("Shodan search JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error")

        parsed = _parse_search(data)
        found = parsed["total"] > 0
        return self._result(identifier, found=found, mode="search", **parsed)
