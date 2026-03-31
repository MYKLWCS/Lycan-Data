"""
vin_decode_enhanced.py — NHTSA extended VIN decode crawler.

Decodes a 17-character VIN using the NHTSA DecodeVinValuesExtended API.
Registered as "vin_decode_enhanced".
"""

from __future__ import annotations

import logging

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}?format=json"

# Error codes that indicate a bad/invalid VIN
_FATAL_ERROR_CODES = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"}


@register("vin_decode_enhanced")
class VinDecodeEnhancedCrawler(HttpxCrawler):
    """
    Decodes a VIN via the NHTSA Extended VIN decode API.
    identifier: 17-character VIN string
    """

    platform = "vin_decode_enhanced"
    category = CrawlerCategory.VEHICLE
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    SOURCE_RELIABILITY = 0.90
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        vin = identifier.strip().upper()
        url = _NHTSA_URL.format(vin=vin)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            payload = resp.json()
        except Exception as exc:
            logger.debug("NHTSA JSON parse error for %s: %s", vin, exc)
            return self._result(identifier, found=False, error="parse_error")

        results = payload.get("Results") or []
        if not results:
            return self._result(identifier, found=False)

        r = results[0]
        error_code = str(r.get("ErrorCode", "0")).strip()
        # Error codes 1-11 are fatal decode failures; 0 = success
        if error_code in _FATAL_ERROR_CODES and r.get("Make", "") == "":
            return self._result(identifier, found=False, error=f"vin_error_{error_code}")

        data = {
            "vin": vin,
            "make": r.get("Make", ""),
            "model": r.get("Model", ""),
            "model_year": r.get("ModelYear", ""),
            "body_class": r.get("BodyClass", ""),
            "drive_type": r.get("DriveType", ""),
            "engine_cylinders": r.get("EngineCylinders", ""),
            "fuel_type": r.get("FuelTypePrimary", ""),
            "gvwr": r.get("GVWR", ""),
            "plant_country": r.get("PlantCountry", ""),
            "series": r.get("Series", ""),
            "trim": r.get("Trim", ""),
            "vehicle_type": r.get("VehicleType", ""),
            "error_code": error_code,
        }
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(data["make"]),
            data=data,
            source_reliability=self.SOURCE_RELIABILITY,
        )
