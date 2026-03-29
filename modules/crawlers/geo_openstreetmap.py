"""
geo_openstreetmap.py — OpenStreetMap geocoding and POI crawler.

For address/place queries: uses Nominatim to geocode and return up to 10 results.
For "lat,lon" coordinate strings: uses Overpass API to retrieve nearby POIs.

No API key required. Nominatim User-Agent header is required.

Registered as "geo_openstreetmap".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_NOMINATIM_URL = (
    "https://nominatim.openstreetmap.org/search?q={query}&format=json&addressdetails=1&limit=10"
)
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nominatim requires a descriptive User-Agent
_HEADERS = {
    "User-Agent": "Lycan-OSINT/1.0 (OSINT research platform; contact@lycan.io)",
    "Accept": "application/json",
}

# Match "lat,lon" with optional spaces and decimal values
_LATLON_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

# Default POI search radius in metres
_OVERPASS_RADIUS = 500


def _is_latlon(value: str) -> tuple[float, float] | None:
    match = _LATLON_RE.match(value)
    if match:
        try:
            return float(match.group(1)), float(match.group(2))
        except ValueError:
            pass
    return None


def _parse_nominatim(results: list[dict]) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    for item in results:
        places.append(
            {
                "display_name": item.get("display_name", ""),
                "lat": item.get("lat", ""),
                "lon": item.get("lon", ""),
                "type": item.get("type", ""),
                "class": item.get("class", ""),
                "importance": item.get("importance"),
                "address": item.get("address", {}),
                "osm_id": item.get("osm_id"),
                "osm_type": item.get("osm_type", ""),
            }
        )
    return places


def _overpass_query(lat: float, lon: float, radius: int = _OVERPASS_RADIUS) -> str:
    """Build an Overpass QL query for nearby nodes, ways, and relations."""
    return (
        f"[out:json][timeout:25];"
        f"(node(around:{radius},{lat},{lon});"
        f"way(around:{radius},{lat},{lon});"
        f"relation(around:{radius},{lat},{lon}););"
        f"out body; >; out skel qt;"
    )


def _parse_overpass(data: dict) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        if not tags:
            continue  # skip bare topology nodes without metadata
        places.append(
            {
                "osm_type": element.get("type", ""),
                "osm_id": element.get("id"),
                "lat": element.get("lat"),
                "lon": element.get("lon"),
                "name": tags.get("name", ""),
                "amenity": tags.get("amenity", ""),
                "shop": tags.get("shop", ""),
                "tourism": tags.get("tourism", ""),
                "tags": tags,
            }
        )
    return places


@register("geo_openstreetmap")
class OpenStreetMapCrawler(HttpxCrawler):
    """
    Geocodes addresses with Nominatim or finds nearby POIs via Overpass.

    identifier: address string, place name  → Nominatim geocoding
                "lat,lon" coordinate string → Overpass POI search

    Data keys returned:
        places — list of result dicts (varies by mode)
        mode   — "geocode" or "overpass"
    """

    platform = "geo_openstreetmap"
    category = CrawlerCategory.GEOSPATIAL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        latlon = _is_latlon(identifier)
        if latlon:
            return await self._scrape_overpass(identifier, latlon[0], latlon[1])
        return await self._scrape_nominatim(identifier)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_nominatim(self, identifier: str) -> CrawlerResult:
        encoded = quote_plus(identifier.strip())
        url = _NOMINATIM_URL.format(query=encoded)
        resp = await self.get(url, headers=_HEADERS)

        if resp is None:
            return self._result(identifier, found=False, error="http_error", places=[])

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited", places=[])

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                places=[],
            )

        try:
            raw = resp.json()
        except Exception as exc:
            logger.warning("Nominatim JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error", places=[])

        places = _parse_nominatim(raw)
        return self._result(identifier, found=len(places) > 0, mode="geocode", places=places)

    async def _scrape_overpass(self, identifier: str, lat: float, lon: float) -> CrawlerResult:
        query = _overpass_query(lat, lon)
        resp = await self.post(
            _OVERPASS_URL,
            data={"data": query},
            headers={"Accept": "application/json"},
        )

        if resp is None:
            return self._result(identifier, found=False, error="http_error", places=[])

        if resp.status_code == 429:
            return self._result(identifier, found=False, error="rate_limited", places=[])

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                places=[],
            )

        try:
            raw = resp.json()
        except Exception as exc:
            logger.warning("Overpass JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error", places=[])

        places = _parse_overpass(raw)
        return self._result(
            identifier,
            found=len(places) > 0,
            mode="overpass",
            lat=lat,
            lon=lon,
            radius_m=_OVERPASS_RADIUS,
            places=places,
        )
