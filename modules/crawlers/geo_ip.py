"""
geo_ip.py — ip-api.com IP geolocation crawler.

Resolves an IP address to geographic, ISP, and proxy/hosting metadata using
the ip-api.com free JSON endpoint. Runs direct (no Tor) because ip-api.com
actively blocks Tor exit nodes.
Registered as "geo_ip".
"""

from __future__ import annotations

import logging

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_IPAPI_URL = (
    "http://ip-api.com/json/{ip}"
    "?fields=status,message,country,countryCode,region,regionName,"
    "city,zip,lat,lon,timezone,isp,org,as,mobile,proxy,hosting,query"
)


@register("geo_ip")
class GeoIPCrawler(HttpxCrawler):
    """
    Geolocates an IP address via ip-api.com, returning country, city, ISP,
    coordinates, timezone, and proxy/hosting/mobile flags.

    ip-api.com blocks Tor exit nodes, so requires_tor is intentionally False.
    source_reliability is 0.85 — ip-api aggregates BGP, WHOIS, and commercial feeds.
    """

    platform = "geo_ip"
    category = CrawlerCategory.GEOSPATIAL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        ip = identifier.strip()
        url = _IPAPI_URL.format(ip=ip)

        response = await self.get(url)

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

        status = json_data.get("status", "fail")
        found = status == "success"

        if not found:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=json_data.get("message", "lookup_failed"),
                source_reliability=self.source_reliability,
            )

        # Omit the raw "status" field from stored data — it's redundant with found
        data = {
            "query": json_data.get("query", ip),
            "country": json_data.get("country"),
            "countryCode": json_data.get("countryCode"),
            "region": json_data.get("region"),
            "regionName": json_data.get("regionName"),
            "city": json_data.get("city"),
            "zip": json_data.get("zip"),
            "lat": json_data.get("lat"),
            "lon": json_data.get("lon"),
            "timezone": json_data.get("timezone"),
            "isp": json_data.get("isp"),
            "org": json_data.get("org"),
            "as": json_data.get("as"),
            "mobile": json_data.get("mobile"),
            "proxy": json_data.get("proxy"),
            "hosting": json_data.get("hosting"),
        }

        return self._result(identifier, found=found, **data)
