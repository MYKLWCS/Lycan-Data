"""
property_county.py — County assessor property record scraper.

Scrapes PropertyShark.com (a publicly accessible aggregator of county
assessor data) via Playwright to retrieve owner info, assessed value,
tax history, and sale records for US properties.

Registered as "property_county".

identifier format: "{address}|{county},{state}"
  e.g. "123 Main St|Cook,IL"
  The county/state portion is optional — bare addresses are accepted.
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

_PROPERTYSHARK_URL = (
    "https://www.propertyshark.com/Real-Estate-Reports/{address}/"
)


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------

def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Split "address|county,state" into (address, county, state).
    Falls back to ("address", "", "") for a bare address.
    """
    if "|" in identifier:
        addr_part, loc_part = identifier.split("|", 1)
        addr_part = addr_part.strip()
        if "," in loc_part:
            county, state = loc_part.split(",", 1)
            return addr_part, county.strip(), state.strip()
        return addr_part, loc_part.strip(), ""
    return identifier.strip(), "", ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_propertyshark_html(html: str) -> dict[str, Any]:
    """
    Parse PropertyShark property report page.

    Extracts: owner_name, assessed_value, tax_amount, year_built,
              lot_size, zoning, last_sale_price, last_sale_date.
    """
    details: dict[str, Any] = {
        "owner_name":      None,
        "assessed_value":  None,
        "tax_amount":      None,
        "year_built":      None,
        "lot_size":        None,
        "zoning":          None,
        "last_sale_price": None,
        "last_sale_date":  None,
    }

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # --- Owner name ---
        # Often inside <span> or <td> labelled "Owner"
        owner_label = soup.find(string=re.compile(r"\bOwner\b", re.I))
        if owner_label:
            parent = owner_label.parent
            nxt = parent.find_next_sibling()
            if nxt:
                details["owner_name"] = nxt.get_text(strip=True) or None

        # --- Assessed value ---
        assessed_label = soup.find(string=re.compile(r"Assessed\s+Value", re.I))
        if assessed_label:
            nxt = assessed_label.parent.find_next_sibling()
            if nxt:
                txt = nxt.get_text(strip=True).replace(",", "").replace("$", "")
                m = re.search(r"\d+", txt)
                if m:
                    details["assessed_value"] = int(m.group())

        # --- Tax amount ---
        tax_label = soup.find(string=re.compile(r"Tax\s+Amount|Annual\s+Tax", re.I))
        if tax_label:
            nxt = tax_label.parent.find_next_sibling()
            if nxt:
                txt = nxt.get_text(strip=True).replace(",", "").replace("$", "")
                m = re.search(r"\d+", txt)
                if m:
                    details["tax_amount"] = int(m.group())

        # --- Year built ---
        year_label = soup.find(string=re.compile(r"Year\s+Built", re.I))
        if year_label:
            nxt = year_label.parent.find_next_sibling()
            if nxt:
                m = re.search(r"\d{4}", nxt.get_text(strip=True))
                if m:
                    details["year_built"] = int(m.group())

        # --- Lot size ---
        lot_label = soup.find(string=re.compile(r"Lot\s+Size|Lot\s+Area", re.I))
        if lot_label:
            nxt = lot_label.parent.find_next_sibling()
            if nxt:
                details["lot_size"] = nxt.get_text(strip=True) or None

        # --- Zoning ---
        zone_label = soup.find(string=re.compile(r"\bZoning\b", re.I))
        if zone_label:
            nxt = zone_label.parent.find_next_sibling()
            if nxt:
                details["zoning"] = nxt.get_text(strip=True) or None

        # --- Last sale price / date ---
        sale_label = soup.find(string=re.compile(r"Last\s+Sale|Sale\s+Price", re.I))
        if sale_label:
            nxt = sale_label.parent.find_next_sibling()
            if nxt:
                txt = nxt.get_text(strip=True).replace(",", "").replace("$", "")
                m = re.search(r"\d+", txt)
                if m:
                    details["last_sale_price"] = int(m.group())
        sale_date_label = soup.find(
            string=re.compile(r"Sale\s+Date|Last\s+Sale\s+Date", re.I)
        )
        if sale_date_label:
            nxt = sale_date_label.parent.find_next_sibling()
            if nxt:
                details["last_sale_date"] = nxt.get_text(strip=True) or None

    except Exception as exc:
        logger.debug("PropertyShark parse error: %s", exc)

    # --- Fallback: regex sweep for common patterns ---
    if details["owner_name"] is None:
        m = re.search(r'"owner"\s*:\s*"([^"]+)"', html, re.I)
        if m:
            details["owner_name"] = m.group(1)

    if details["assessed_value"] is None:
        m = re.search(r'assessed[^"]*value[^"]*"\s*:\s*"?\$?([\d,]+)', html, re.I)
        if m:
            details["assessed_value"] = int(m.group(1).replace(",", ""))

    return details


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("property_county")
class PropertyCountyCrawler(PlaywrightCrawler):
    """
    Scrapes county assessor data for US properties via PropertyShark.

    identifier: "{address}|{county},{state}" or bare address string.

    Data keys returned:
        owner_name, assessed_value, tax_amount, year_built, lot_size,
        zoning, last_sale_price, last_sale_date, address
    """

    platform = "property_county"
    source_reliability = 0.85
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        address, county, state = _parse_identifier(identifier)

        url = _PROPERTYSHARK_URL.format(address=quote_plus(address))
        details = await self._scrape_propertyshark(url)
        details["address"] = address

        found = any(
            v is not None
            for k, v in details.items()
            if k != "address"
        )

        return self._result(
            identifier,
            found=found,
            **details,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_propertyshark(self, url: str) -> dict[str, Any]:
        """Navigate to PropertyShark URL and parse the property report."""
        try:
            async with self.page(url) as page:
                await page.wait_for_load_state("networkidle", timeout=25000)
                html = await page.content()
            return _parse_propertyshark_html(html)
        except Exception as exc:
            logger.warning("PropertyShark scrape error: %s", exc)
            return {
                "owner_name":      None,
                "assessed_value":  None,
                "tax_amount":      None,
                "year_built":      None,
                "lot_size":        None,
                "zoning":          None,
                "last_sale_price": None,
                "last_sale_date":  None,
            }
