"""
geo_adsbexchange.py — Aircraft registration lookup via adsbdb.com free API.

Resolves an aircraft registration (N-number, G-reg, etc.) to type,
manufacturer, operator, country, and ICAO hex code information.
Registered as "geo_adsbexchange".
"""
from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_AIRCRAFT_URL = "https://api.adsbdb.com/v0/aircraft/{registration}"


def _normalise_registration(reg: str) -> str:
    """Strip leading/trailing whitespace and normalise to uppercase."""
    return reg.strip().upper()


def _parse_aircraft(payload: dict) -> dict[str, Any]:
    """
    Extract aircraft fields from adsbdb response.

    adsbdb wraps data under {"response": {"aircraft": {...}}}
    """
    response_block = payload.get("response", {})
    aircraft = response_block.get("aircraft", {})
    if not aircraft:
        # Some endpoints return aircraft directly at response level
        aircraft = response_block

    return {
        "registration": aircraft.get("registration", ""),
        "type": aircraft.get("type", ""),
        "manufacturer": aircraft.get("manufacturer", ""),
        "operator": aircraft.get("registered_owner", "")
                    or aircraft.get("operator", ""),
        "country": aircraft.get("registered_owner_country_name", "")
                   or aircraft.get("country", ""),
        "modes": aircraft.get("mode_s", "")
                 or aircraft.get("icao_hex", ""),
        "url": aircraft.get("url", ""),
    }


@register("geo_adsbexchange")
class GeoAdsbexchangeCrawler(HttpxCrawler):
    """
    Looks up aircraft registration data via adsbdb.com (free, no auth).

    identifier: aircraft registration (e.g. "N12345", "G-ABCD")

    Data keys returned:
        registration    — normalised registration string
        type            — aircraft type/model
        manufacturer    — aircraft manufacturer
        operator        — registered owner or operator
        country         — country of registration
        modes           — ICAO hex code(s)
        url             — adsbdb detail URL
    """

    platform = "geo_adsbexchange"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        registration = _normalise_registration(identifier)
        url = _AIRCRAFT_URL.format(registration=registration)

        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                registration=registration,
                type="",
                manufacturer="",
                operator="",
                country="",
                modes="",
            )

        if resp.status_code == 404:
            return self._result(
                identifier,
                found=False,
                error="registration_not_found",
                registration=registration,
                type="",
                manufacturer="",
                operator="",
                country="",
                modes="",
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                registration=registration,
                type="",
                manufacturer="",
                operator="",
                country="",
                modes="",
            )

        try:
            payload = resp.json()
        except Exception:
            return self._result(
                identifier,
                found=False,
                error="invalid_json",
                registration=registration,
                type="",
                manufacturer="",
                operator="",
                country="",
                modes="",
            )

        aircraft = _parse_aircraft(payload)

        # Consider found if we got at least a registration or type back
        found = bool(aircraft.get("registration") or aircraft.get("type"))

        return self._result(
            identifier,
            found=found,
            **aircraft,
        )
