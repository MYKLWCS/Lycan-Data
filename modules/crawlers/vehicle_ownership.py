"""
vehicle_ownership.py — Vehicle ownership lookup via people-search aggregators.

Finds what vehicles a person owns by scraping public aggregator sites.
Uses Playwright for JS-heavy pages.

Registered as "vehicle_ownership".

identifier format: "FirstName LastName|City,State"
  e.g. "John Smith|Austin,TX"
  City/State portion is optional.

Sources:
  1. vehiclehistory.com/owners/ — HTML scrape (Playwright)
  2. beenverified.com/people/  — HTML scrape (Playwright, vehicle section)
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_VEHHISTORY_OWNER_URL = "https://www.vehiclehistory.com/owners/{first}-{last}/"
_BEENVERIFIED_URL = "https://www.beenverified.com/people/{first}-{last}/"


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------


def _parse_identifier(identifier: str) -> tuple[str, str, str, str]:
    """
    Split "First Last|City,State" into (first, last, city, state).
    Falls back gracefully when optional parts are missing.
    """
    name_part = identifier
    city = state = ""

    if "|" in identifier:
        name_part, loc_part = identifier.split("|", 1)
        if "," in loc_part:
            city, state = loc_part.split(",", 1)
            city = city.strip()
            state = state.strip()
        else:
            city = loc_part.strip()

    name_part = name_part.strip()
    parts = name_part.split()
    if len(parts) >= 2:
        first = parts[0]
        last = parts[-1]
    elif parts:
        first = parts[0]
        last = ""
    else:
        first = last = ""

    return first, last, city, state


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_vehicle_cards_html(html: str) -> list[dict[str, Any]]:
    """
    Parse HTML from vehicle ownership pages.
    Looks for vehicle card patterns common to aggregator sites.
    """
    vehicles: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Look for vehicle blocks — common selectors used by aggregators
        selectors = [
            {"class": re.compile(r"vehicle-card|vehicle-item|car-record", re.I)},
            {"class": re.compile(r"result-vehicle|vehicle-result|owned-vehicle", re.I)},
            {"data-type": re.compile(r"vehicle|car|auto", re.I)},
        ]

        vehicle_els = []
        for sel in selectors:
            vehicle_els = soup.find_all(attrs=sel)
            if vehicle_els:
                break

        for el in vehicle_els[:10]:
            text = el.get_text(" ", strip=True)
            v: dict[str, Any] = {}

            year_m = re.search(r"\b(19[7-9]\d|20[0-2]\d)\b", text)
            if year_m:
                v["year"] = year_m.group(1)

            vin_m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text)
            if vin_m:
                v["vin"] = vin_m.group(1)

            plate_m = re.search(r"(?:Plate|License)[:\s]+([A-Z0-9\-]{4,10})", text, re.I)
            if plate_m:
                v["plate"] = plate_m.group(1).strip()

            state_m = re.search(r"(?:State|Reg)[:\s]+([A-Z]{2})\b", text, re.I)
            if state_m:
                v["state"] = state_m.group(1)

            make_m = re.search(r"(?:Make|Brand)[:\s]+([A-Za-z]+)", text, re.I)
            if make_m:
                v["make"] = make_m.group(1)

            model_m = re.search(r"(?:Model)[:\s]+([A-Za-z0-9\s]+?)(?:\s{2,}|\|)", text, re.I)
            if model_m:
                v["model"] = model_m.group(1).strip()

            color_m = re.search(r"(?:Color|Colour)[:\s]+([A-Za-z]+)", text, re.I)
            if color_m:
                v["color"] = color_m.group(1)

            if v:
                vehicles.append(v)

        # Regex sweep fallback if no structured elements found
        if not vehicles:
            for block in re.finditer(
                r"((?:19[7-9]\d|20[0-2]\d)\s+[A-Za-z]+\s+[A-Za-z0-9]+)",
                html,
            ):
                parts = block.group(1).split()
                if len(parts) >= 3:
                    vehicles.append(
                        {
                            "year": parts[0],
                            "make": parts[1],
                            "model": " ".join(parts[2:]),
                        }
                    )
                if len(vehicles) >= 10:
                    break

    except Exception as exc:
        logger.debug("vehicle ownership HTML parse error: %s", exc)

    return vehicles


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("vehicle_ownership")
class VehicleOwnershipCrawler(PlaywrightCrawler):
    """
    Finds vehicles owned by a person via aggregator sites.

    identifier: "FirstName LastName|City,State"

    Data keys returned:
        owner_name, vehicles (list of {make, model, year, plate, state, vin, color})
    """

    platform = "vehicle_ownership"
    source_reliability = 0.60
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        first, last, city, state = _parse_identifier(identifier)

        if not first:
            return self._result(identifier, found=False, error="invalid_identifier", vehicles=[])

        owner_name = f"{first} {last}".strip()
        all_vehicles: list[dict[str, Any]] = []

        # --- Source 1: vehiclehistory.com/owners/ ---
        vh_vehicles = await self._scrape_vehiclehistory(first, last)
        all_vehicles.extend(vh_vehicles)

        # --- Source 2: beenverified.com (vehicle section) ---
        if len(all_vehicles) < 3:
            bv_vehicles = await self._scrape_beenverified(first, last)
            # Merge — avoid duplicates by VIN
            existing_vins = {v.get("vin") for v in all_vehicles if v.get("vin")}
            for v in bv_vehicles:
                if v.get("vin") and v["vin"] in existing_vins:
                    continue
                all_vehicles.append(v)
                if v.get("vin"):
                    existing_vins.add(v["vin"])

        return self._result(
            identifier,
            found=len(all_vehicles) > 0,
            owner_name=owner_name,
            vehicles=all_vehicles,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_vehiclehistory(self, first: str, last: str) -> list[dict[str, Any]]:
        """Scrape vehiclehistory.com/owners/ page."""
        if not last:
            return []
        url = _VEHHISTORY_OWNER_URL.format(
            first=quote_plus(first.lower()),
            last=quote_plus(last.lower()),
        )
        try:
            async with self.page(url) as page:
                await page.wait_for_load_state("networkidle", timeout=25000)
                html = await page.content()
            return _parse_vehicle_cards_html(html)
        except Exception as exc:
            logger.warning("vehiclehistory owner scrape error: %s", exc)
            return []

    async def _scrape_beenverified(self, first: str, last: str) -> list[dict[str, Any]]:
        """Scrape BeenVerified people page for vehicle section."""
        if not last:
            return []
        url = _BEENVERIFIED_URL.format(
            first=quote_plus(first.lower()),
            last=quote_plus(last.lower()),
        )
        try:
            async with self.page(url) as page:
                await page.wait_for_load_state("networkidle", timeout=30000)
                # Try to expand vehicle section if present
                try:
                    vehicles_section = page.locator(
                        "section:has-text('Vehicles'), div:has-text('Vehicles Owned')"
                    ).first
                    await vehicles_section.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
                html = await page.content()
            return _parse_vehicle_cards_html(html)
        except Exception as exc:
            logger.warning("beenverified vehicle scrape error: %s", exc)
            return []
