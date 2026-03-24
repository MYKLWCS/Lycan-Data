"""
Google Maps / Location Intelligence crawler.

Uses Nominatim (OpenStreetMap geocoding — free, no API key) to resolve
person names and business names to geographic locations. Also scrapes
Google Search Knowledge Graph for address/phone data.
"""
from __future__ import annotations

import logging
from urllib.parse import quote, quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@register("google_maps")
class GoogleMapsCrawler(HttpxCrawler):
    """
    Extracts location intelligence for a person or business name.

    Combines:
    - Nominatim (OSM geocoding) for lat/lon + structured address
    - Google Search Knowledge Graph HTML for phone, hours, website, rating

    identifier format: person name or business name, e.g. "Tesla Inc Palo Alto"
    """

    platform = "google_maps"
    source_reliability = 0.70
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        locations: list[dict] = []

        # ── Nominatim geocoding ────────────────────────────────────────────────
        nominatim_results = await self._query_nominatim(query)
        locations.extend(nominatim_results)

        # ── Google Knowledge Graph (best-effort HTML scrape) ───────────────────
        kg_location = await self._scrape_google_kg(query)
        if kg_location:
            # Merge or add — avoid duplicate if nominatim already found same address
            locations.append(kg_location)

        return self._result(
            identifier=identifier,
            found=True,
            locations=locations,
            query=query,
        )

    # ── Nominatim ──────────────────────────────────────────────────────────────

    async def _query_nominatim(self, query: str) -> list[dict]:
        """Query Nominatim for geocoding results."""
        params = {
            "q": query,
            "format": "json",
            "addressdetails": "1",
            "limit": "5",
        }
        param_str = "&".join(f"{k}={quote(v)}" for k, v in params.items())
        url = f"{NOMINATIM_URL}?{param_str}"

        response = await self.get(
            url,
            headers={
                "User-Agent": "LycanOSINT/1.0 (research tool; contact@lycan.local)",
                "Accept-Language": "en",
            },
        )
        if not response or response.status_code != 200:
            logger.warning("Nominatim request failed for query: %s", query)
            return []

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("Nominatim JSON parse error: %s", exc)
            return []

        if not isinstance(data, list):
            return []

        return [_parse_nominatim_result(item) for item in data if item]

    # ── Google Knowledge Graph (HTML scrape) ──────────────────────────────────

    async def _scrape_google_kg(self, query: str) -> dict | None:
        """Scrape Google Search for address/phone in the Knowledge Graph panel."""
        encoded = quote_plus(f"{query} address location phone")
        url = f"https://www.google.com/search?q={encoded}&hl=en"

        response = await self.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if not response or response.status_code != 200:
            logger.warning("Google KG request failed for query: %s", query)
            return None

        return _parse_google_kg(response.text, query)


# ── Parsers ────────────────────────────────────────────────────────────────────


def _parse_nominatim_result(item: dict) -> dict:
    """Convert a single Nominatim JSON result to our location schema."""
    address = item.get("address", {})
    # Build human-readable address
    parts = []
    for field in ("house_number", "road", "suburb", "city", "town", "village",
                  "state", "postcode", "country"):
        val = address.get(field)
        if val:
            parts.append(val)
    address_str = ", ".join(parts) if parts else item.get("display_name", "")

    return {
        "name": item.get("display_name", ""),
        "address": address_str,
        "lat": float(item.get("lat", 0)) if item.get("lat") else None,
        "lon": float(item.get("lon", 0)) if item.get("lon") else None,
        "type": item.get("type", "unknown"),
        "phone": None,  # Nominatim doesn't return phone
    }


def _parse_google_kg(html: str, query: str) -> dict | None:
    """
    Extract address and contact info from Google Knowledge Graph panel.
    Returns None if nothing useful is found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Google KG panel selectors (subject to change with Google's HTML)
    address = None
    phone = None

    # Address: often in span with data attributes or known class patterns
    for selector in [
        "[data-attrid='kc:/location/location:address']",
        ".LrzXr",
        "[data-attrid='ss:/webfacts:phone_number']",
    ]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            if text:
                address = text
                break

    # Phone: look for tel: links or phone patterns
    tel_link = soup.find("a", href=lambda h: h and h.startswith("tel:"))
    if tel_link:
        phone = tel_link.get("href", "").replace("tel:", "").strip()

    if not address and not phone:
        return None

    return {
        "name": query,
        "address": address or "",
        "lat": None,
        "lon": None,
        "type": "knowledge_graph",
        "phone": phone,
    }
