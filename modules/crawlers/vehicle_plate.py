"""
vehicle_plate.py — License plate lookup scraper.

Attempts to resolve a US license plate to vehicle details by trying
multiple free public sources in priority order.

Registered as "vehicle_plate".

identifier format: "{PLATE}|{STATE}"
  e.g. "ABC1234|TX"

Sources (tried in order):
  1. faxvin.com   — JSON API endpoint (fastest)
  2. licenseplatedata.com — HTML scrape
  3. vehiclehistory.com   — HTML scrape (fallback)
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_FAXVIN_URL = "https://faxvin.com/license-plate-lookup/result?plate={plate}&state={state}"
_PLATEDATA_URL = "https://www.licenseplatedata.com/license-plate/{state}/{plate}/"
_VEHHISTORY_URL = "https://www.vehiclehistory.com/license-plate-search/?plate={plate}&state={state}"


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str]:
    """
    Split "PLATE|STATE" into (plate, state).
    Returns (identifier, "") if no pipe present.
    """
    if "|" in identifier:
        plate, state = identifier.split("|", 1)
        return plate.strip().upper(), state.strip().upper()
    return identifier.strip().upper(), ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_faxvin_json(data: dict) -> dict[str, Any]:
    """Parse faxvin JSON response into normalised vehicle dict."""
    result: dict[str, Any] = {}
    # faxvin may nest under various keys
    vehicle = data.get("vehicle") or data.get("data") or data
    if isinstance(vehicle, dict):
        result["year"] = str(vehicle.get("year", "")) or None
        result["make"] = vehicle.get("make") or None
        result["model"] = vehicle.get("model") or None
        result["vin"] = vehicle.get("vin") or None
        result["color"] = vehicle.get("color") or vehicle.get("exterior_color") or None
        result["body_style"] = vehicle.get("body_style") or vehicle.get("body_class") or None
    return {k: v for k, v in result.items() if v}


def _parse_licenseplatedata_html(html: str) -> dict[str, Any]:
    """
    Parse licenseplatedata.com response HTML.
    Looks for <div class="result-value"> elements paired with labels.
    """
    result: dict[str, Any] = {}
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Try structured result-value divs
        labels = soup.find_all(class_=re.compile(r"result-label|label", re.I))
        values = soup.find_all(class_=re.compile(r"result-value|value", re.I))
        for label_el, value_el in zip(labels, values, strict=False):
            key = label_el.get_text(strip=True).lower().replace(" ", "_").rstrip(":")
            value = value_el.get_text(strip=True)
            if value:
                result[key] = value

        # Fallback: regex for common patterns in the HTML
        if not result:
            for pattern, field in [
                (r"(?:Year|Model Year)[:\s]+(\d{4})", "year"),
                (r"Make[:\s]+([A-Za-z]+)", "make"),
                (r"Model[:\s]+([A-Za-z0-9\s]+?)[\n<]", "model"),
                (r"VIN[:\s]+([A-HJ-NPR-Z0-9]{17})", "vin"),
                (r"Color[:\s]+([A-Za-z]+)", "color"),
            ]:
                m = re.search(pattern, html, re.I)
                if m:
                    result[field] = m.group(1).strip()

    except Exception as exc:
        logger.debug("licenseplatedata parse error: %s", exc)

    return result


def _parse_vehiclehistory_html(html: str) -> dict[str, Any]:
    """Parse vehiclehistory.com plate search result HTML."""
    result: dict[str, Any] = {}
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # vehiclehistory wraps vehicle info in data-* attributes or span tags
        for span in soup.find_all("span", {"class": re.compile(r"vehicle|plate|result", re.I)}):
            text = span.get_text(strip=True)
            if re.match(r"\d{4}", text):
                result["year"] = text[:4]
            elif re.match(r"^[A-HJ-NPR-Z0-9]{17}$", text):  # pragma: no branch
                result["vin"] = text

        # Regex fallback
        for pattern, field in [
            (r'"year"\s*:\s*"?(\d{4})"?', "year"),
            (r'"make"\s*:\s*"([^"]+)"', "make"),
            (r'"model"\s*:\s*"([^"]+)"', "model"),
            (r'"vin"\s*:\s*"([A-HJ-NPR-Z0-9]{17})"', "vin"),
            (r'"color"\s*:\s*"([^"]+)"', "color"),
        ]:
            m = re.search(pattern, html, re.I)
            if m:
                result.setdefault(field, m.group(1).strip())

    except Exception as exc:
        logger.debug("vehiclehistory parse error: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("vehicle_plate")
class VehiclePlateCrawler(HttpxCrawler):
    """
    Resolves a US license plate to vehicle details.

    identifier: "{PLATE}|{STATE}" e.g. "ABC1234|TX"

    Data keys returned:
        plate, state, vin, make, model, year, color, body_style, source
    """

    platform = "vehicle_plate"
    category = CrawlerCategory.VEHICLE
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.65
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        plate, state = _parse_identifier(identifier)

        if not plate:
            return self._result(identifier, found=False, error="invalid_identifier")

        vehicle: dict[str, Any] = {"plate": plate, "state": state}
        source_used = ""

        # --- Source 1: faxvin JSON ---
        faxvin_url = _FAXVIN_URL.format(plate=quote_plus(plate), state=state.lower())
        resp = await self.get(faxvin_url)
        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
                parsed = _parse_faxvin_json(data)
                if parsed:
                    vehicle.update(parsed)
                    source_used = "faxvin"
            except Exception as exc:
                logger.debug("faxvin JSON parse error: %s", exc)

        # --- Source 2: licenseplatedata HTML (fallback) ---
        if not source_used:
            lpd_url = _PLATEDATA_URL.format(state=state.lower(), plate=plate.lower())
            resp2 = await self.get(lpd_url)
            if resp2 is not None and resp2.status_code == 200:
                parsed2 = _parse_licenseplatedata_html(resp2.text)
                if parsed2:  # pragma: no branch
                    vehicle.update(parsed2)
                    source_used = "licenseplatedata"

        # --- Source 3: vehiclehistory HTML (last resort) ---
        if not source_used:
            vh_url = _VEHHISTORY_URL.format(plate=quote_plus(plate), state=state.lower())
            resp3 = await self.get(vh_url)
            if resp3 is not None and resp3.status_code == 200:
                parsed3 = _parse_vehiclehistory_html(resp3.text)
                if parsed3:
                    vehicle.update(parsed3)
                    source_used = "vehiclehistory"

        vehicle["source"] = source_used or "none"

        found = bool(vehicle.get("make") or vehicle.get("vin") or vehicle.get("model"))
        return self._result(identifier, found=found, **vehicle)
