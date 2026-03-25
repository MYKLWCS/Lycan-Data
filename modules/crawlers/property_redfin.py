"""
property_redfin.py — Redfin property listing and history crawler.

Uses the Redfin internal stingray API (unofficial, no auth required) to:
  1. Resolve the address via autocomplete to get a regionId / listingId
  2. Fetch GIS/listing data for that result

Returns a list of matching properties with price, beds, baths, sqft, etc.
Registered as "property_redfin".
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_AUTOCOMPLETE_URL = (
    "https://www.redfin.com/stingray/api/location/autocomplete?location={address}&v=2"
)
_GIS_CSV_URL = (
    "https://www.redfin.com/stingray/api/gis-csv"
    "?al=1&market=national&num_homes=10&uipt=1,2,3,4&v=8&q={address}"
)
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.redfin.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Redfin wraps JSON responses with "{}&&" prefix (XSSI guard)
_XSSI_RE = re.compile(r"^\s*\{\}\s*&&\s*")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _strip_xssi(text: str) -> str:
    return _XSSI_RE.sub("", text, count=1).strip()


def _parse_autocomplete(data: dict) -> list[dict[str, Any]]:
    """Extract address stubs from the autocomplete payload."""
    items = []
    for section in data.get("payload", {}).get("sections", []):
        for row in section.get("rows", []):
            items.append(
                {
                    "address": row.get("name", ""),
                    "subtext": row.get("subtext", ""),
                    "url": row.get("url", ""),
                    "id": row.get("id", ""),
                    "type": row.get("type", ""),
                }
            )
    return items


def _parse_csv_property(row: dict) -> dict[str, Any]:
    """Normalise a single row from the GIS CSV response (already parsed as dict)."""

    def _int(val: Any) -> int | None:
        try:
            return int(val) if val not in (None, "", "N/A") else None
        except (TypeError, ValueError):
            return None

    def _float(val: Any) -> float | None:
        try:
            return float(str(val).replace(",", "")) if val not in (None, "", "N/A") else None
        except (TypeError, ValueError):
            return None

    return {
        "mlsId": row.get("MLS#") or row.get("mlsId"),
        "price": _float(row.get("PRICE") or row.get("price")),
        "beds": _int(row.get("BEDS") or row.get("beds")),
        "baths": _float(row.get("BATHS") or row.get("baths")),
        "sqFt": _int(row.get("SQFT") or row.get("sqFt")),
        "address": row.get("ADDRESS") or row.get("address", ""),
        "yearBuilt": _int(row.get("YEAR BUILT") or row.get("yearBuilt")),
        "daysOnMarket": _int(row.get("DAYS ON MARKET") or row.get("daysOnMarket")),
        "lastSoldPrice": _float(row.get("LAST SOLD PRICE") or row.get("lastSoldPrice")),
        "lastSoldDate": row.get("LAST SOLD DATE") or row.get("lastSoldDate"),
        "status": row.get("STATUS") or row.get("status", ""),
        "url": row.get("URL") or row.get("url", ""),
    }


def _parse_csv_text(text: str) -> list[dict[str, Any]]:
    """Parse Redfin CSV (or JSON) GIS response into property dicts."""
    properties: list[dict[str, Any]] = []
    try:
        # Some responses are JSON with an embedded CSV string
        if text.strip().startswith("{"):
            data = json.loads(_strip_xssi(text))
            payload = data.get("payload", {})
            homes = payload.get("homes", payload.get("rows", []))
            for home in homes:
                properties.append(_parse_csv_property(home))
            return properties

        # Plain CSV
        import csv
        import io

        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            properties.append(_parse_csv_property(dict(row)))
    except Exception as exc:
        logger.warning("Redfin GIS parse error: %s", exc)

    return properties


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("property_redfin")
class PropertyRedfinCrawler(HttpxCrawler):
    """
    Queries Redfin for property listings by address.

    identifier: property address string, e.g. "123 Main St, Austin TX 78701".

    Returns a list of properties with MLS id, price, beds, baths, sqft,
    address, yearBuilt, daysOnMarket, lastSoldPrice, and lastSoldDate.

    source_reliability: 0.80 — Redfin pulls live MLS data, highly accurate.
    """

    platform = "property_redfin"
    source_reliability = 0.80
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        encoded = quote_plus(address)

        # Step 1: Autocomplete to validate / resolve address
        ac_url = _AUTOCOMPLETE_URL.format(address=encoded)
        ac_response = await self.get(ac_url, headers=_HEADERS)

        autocomplete_results: list[dict[str, Any]] = []
        if ac_response is not None and ac_response.status_code == 200:  # pragma: no branch
            try:
                raw = _strip_xssi(ac_response.text)
                ac_data = json.loads(raw)
                autocomplete_results = _parse_autocomplete(ac_data)
            except Exception as exc:
                logger.debug("Redfin autocomplete parse error: %s", exc)

        # Step 2: Fetch GIS listing data
        gis_url = _GIS_CSV_URL.format(address=encoded)
        gis_response = await self.get(gis_url, headers=_HEADERS)

        if gis_response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if gis_response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if gis_response.status_code not in (200, 206):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{gis_response.status_code}",
                source_reliability=self.source_reliability,
            )

        properties = _parse_csv_text(gis_response.text)
        found = len(properties) > 0

        return self._result(
            identifier,
            found=found,
            properties=properties,
            autocomplete=autocomplete_results,
            query=address,
        )
