"""
vehicle_nhtsa.py — NHTSA VIN decoder and recall lookup.

Decodes a 17-character Vehicle Identification Number (VIN) using the
NHTSA free public API, then cross-checks for open safety recalls.

Registered as "vehicle_nhtsa".

identifier: VIN string (17 alphanumeric characters, no I/O/Q)
  e.g. "1HGBH41JXMN109186"
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
_RECALLS_URL = (
    "https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
)

# Fields we care about from the flat key-value array
_WANTED_VARS = {
    "Make": "make",
    "Model": "model",
    "Model Year": "year",
    "Body Class": "body_class",
    "Engine Configuration": "engine",
    "Fuel Type - Primary": "fuel_type",
    "Manufacturer Name": "manufacturer",
    "Plant Country": "plant_country",
    "Plant State": "plant_state",
    "Vehicle Type": "vehicle_type",
    "Drive Type": "drive_type",
    "Transmission Style": "transmission",
}


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _validate_vin(vin: str) -> bool:
    """VIN must be exactly 17 alphanumeric chars, no I/O/Q."""
    return bool(re.match(r"^[A-HJ-NPR-Z0-9]{17}$", vin.upper()))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_decode_results(results: list[dict]) -> dict[str, Any]:
    """
    Convert the NHTSA flat {Variable, Value, ValueId} array into a clean dict.
    Only extracts the fields listed in _WANTED_VARS; skips empty/null values.
    """
    data: dict[str, Any] = {}
    for item in results:
        var_name = item.get("Variable", "")
        value = item.get("Value") or ""
        if (
            var_name in _WANTED_VARS
            and value
            and value.lower() not in ("not applicable", "null", "none")
        ):
            data[_WANTED_VARS[var_name]] = value
    return data


def _parse_recalls(recall_results: list[dict]) -> list[dict[str, Any]]:
    """Extract recall summaries from NHTSA recalls response."""
    recalls: list[dict[str, Any]] = []
    for r in recall_results:
        recalls.append(
            {
                "component": r.get("Component", ""),
                "summary": r.get("Summary", ""),
                "consequence": r.get("Consequence", ""),
                "remedy": r.get("Remedy", ""),
                "campaign_id": r.get("NHTSACampaignNumber", ""),
            }
        )
    return recalls


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("vehicle_nhtsa")
class VehicleNhtsaCrawler(HttpxCrawler):
    """
    Decodes a VIN via the NHTSA free public API and fetches open recalls.

    identifier: 17-character VIN string.

    Data keys returned:
        vin, make, model, year, body_class, engine, fuel_type, manufacturer,
        plant_country, plant_state, vehicle_type, drive_type, transmission,
        recalls (list of {component, summary, consequence, remedy, campaign_id})
    """

    platform = "vehicle_nhtsa"
    category = CrawlerCategory.VEHICLE
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.92
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        vin = identifier.strip().upper()

        if not _validate_vin(vin):
            return self._result(
                identifier,
                found=False,
                error="invalid_vin",
                vin=vin,
                recalls=[],
            )

        # --- Primary: VIN decode ---
        decode_url = _DECODE_URL.format(vin=vin)
        resp = await self.get(decode_url)

        if resp is None:
            return self._result(identifier, found=False, error="http_error", vin=vin, recalls=[])

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                vin=vin,
                recalls=[],
            )

        try:
            payload = resp.json()
        except Exception as exc:
            logger.warning("NHTSA VIN decode JSON parse error: %s", exc)
            return self._result(
                identifier, found=False, error="json_parse_error", vin=vin, recalls=[]
            )

        results = payload.get("Results", [])
        vehicle_data = _parse_decode_results(results)
        vehicle_data["vin"] = vin

        if not vehicle_data.get("make"):
            # NHTSA returns data for every VIN, even invalid ones — "make" absent = bad VIN
            return self._result(identifier, found=False, error="vin_not_found", vin=vin, recalls=[])

        # --- Secondary: Recalls lookup ---
        recalls: list[dict[str, Any]] = []
        make = vehicle_data.get("make", "")
        model = vehicle_data.get("model", "")
        year = vehicle_data.get("year", "")

        if make and model and year:  # pragma: no branch
            recalls_url = _RECALLS_URL.format(
                make=quote_plus(make),
                model=quote_plus(model),
                year=quote_plus(year),
            )
            recalls_resp = await self.get(recalls_url)
            if recalls_resp is not None and recalls_resp.status_code == 200:
                try:
                    recalls_payload = recalls_resp.json()
                    raw_recalls = recalls_payload.get("results", recalls_payload.get("Results", []))
                    recalls = _parse_recalls(raw_recalls)
                except Exception as exc:
                    logger.debug("NHTSA recalls parse error: %s", exc)

        vehicle_data["recalls"] = recalls

        return self._result(identifier, found=True, **vehicle_data)
