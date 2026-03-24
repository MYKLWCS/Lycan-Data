"""
property_zillow.py — Zillow property record scraper.

Uses Zillow's suggestion API to resolve addresses, then scrapes property
pages via Playwright for Zestimate, beds/baths, sqft, and sale history.

Registered as "property_zillow".
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

_SUGGEST_URL = (
    "https://www.zillowstatic.com/autocomplete/v3/suggestions"
    "?q={query}&resultCount=5"
)
_PROPERTY_URL = "https://www.zillow.com/homes/{address}_rb/"

_MAX_RESULTS = 5


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_suggestions(data: dict) -> list[dict[str, Any]]:
    """
    Parse Zillow autocomplete suggestions into normalised property stubs.

    JSON shape:
        {results: [{display, metaData: {addressCity, addressState,
                                        addressZip, lat, lng, zpid}}]}
    """
    properties: list[dict[str, Any]] = []
    for item in data.get("results", [])[:_MAX_RESULTS]:
        meta = item.get("metaData", {})
        properties.append(
            {
                "address":    item.get("display", ""),
                "city":       meta.get("addressCity", ""),
                "state":      meta.get("addressState", ""),
                "zip":        meta.get("addressZip", ""),
                "lat":        meta.get("lat"),
                "lng":        meta.get("lng"),
                "zpid":       meta.get("zpid"),
                # detail fields populated by _parse_property_page
                "zestimate":       None,
                "beds":            None,
                "baths":           None,
                "sqft":            None,
                "last_sold_price": None,
                "last_sold_date":  None,
            }
        )
    return properties


def _parse_property_page(html: str) -> dict[str, Any]:
    """
    Extract property details from a Zillow property page HTML.

    Zillow embeds a JSON blob inside a <script id="__NEXT_DATA__"> tag.
    We pull what we can from that, falling back to regex patterns.
    """
    details: dict[str, Any] = {
        "zestimate":       None,
        "beds":            None,
        "baths":           None,
        "sqft":            None,
        "last_sold_price": None,
        "last_sold_date":  None,
    }

    # --- Try to extract Next.js page props JSON ---
    try:
        import json

        match = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if match:
            page_data = json.loads(match.group(1))
            props = (
                page_data.get("props", {})
                .get("pageProps", {})
                .get("componentProps", {})
                .get("gdpClientCache", {})
            )
            # The gdpClientCache is a JSON-string-encoded dict
            if isinstance(props, str):
                props = json.loads(props)
            for _key, val in props.items():
                if not isinstance(val, dict):
                    continue
                home = val.get("property", val)
                if "zestimate" in home:
                    details["zestimate"] = home.get("zestimate")
                if "bedrooms" in home:
                    details["beds"] = home.get("bedrooms")
                if "bathrooms" in home:
                    details["baths"] = home.get("bathrooms")
                if "livingArea" in home:
                    details["sqft"] = home.get("livingArea")
                price_hist = home.get("priceHistory", [])
                if price_hist:
                    last = price_hist[0]
                    details["last_sold_price"] = last.get("price")
                    details["last_sold_date"] = last.get("date")
                break
    except Exception as exc:
        logger.debug("Zillow JSON parse error: %s", exc)

    # --- Fallback: regex scrape for common patterns ---
    if details["zestimate"] is None:
        m = re.search(r'"zestimate"\s*:\s*(\d+)', html)
        if m:
            details["zestimate"] = int(m.group(1))

    if details["beds"] is None:
        m = re.search(r'"bedrooms"\s*:\s*(\d+)', html)
        if m:
            details["beds"] = int(m.group(1))

    if details["baths"] is None:
        m = re.search(r'"bathrooms"\s*:\s*([\d.]+)', html)
        if m:
            details["baths"] = float(m.group(1))

    if details["sqft"] is None:
        m = re.search(r'"livingArea"\s*:\s*(\d+)', html)
        if m:
            details["sqft"] = int(m.group(1))

    return details


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("property_zillow")
class PropertyZillowCrawler(PlaywrightCrawler):
    """
    Scrapes Zillow for property records by owner name or address.

    identifier: address string, e.g. "123 Main St, Austin TX 78701"

    Data keys returned:
        properties   — list of {address, zestimate, beds, baths, sqft,
                                last_sold_price, last_sold_date, zpid}
        query        — original identifier
    """

    platform = "property_zillow"
    source_reliability = 0.70
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        # Step 1: resolve address via autocomplete API
        suggest_url = _SUGGEST_URL.format(query=quote_plus(query))
        properties = await self._fetch_suggestions(suggest_url)

        if not properties:
            return self._result(
                identifier,
                found=False,
                properties=[],
                query=query,
            )

        # Step 2: enrich first result with property page details
        top = properties[0]
        if top.get("address"):
            page_details = await self._fetch_property_page(top["address"])
            top.update(page_details)

        return self._result(
            identifier,
            found=True,
            properties=properties,
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_suggestions(self, url: str) -> list[dict[str, Any]]:
        """Call the Zillow autocomplete API via Playwright (for cookie handling)."""
        try:
            async with self.page() as page:
                # Inject a simple fetch call to bypass bot checks
                resp = await page.evaluate(
                    f"""async () => {{
                        const r = await fetch({url!r},
                            {{headers: {{'Accept': 'application/json'}}}});
                        return r.json();
                    }}"""
                )
            return _parse_suggestions(resp if isinstance(resp, dict) else {})
        except Exception as exc:
            logger.warning("Zillow suggestions error: %s", exc)
            return []

    async def _fetch_property_page(self, address: str) -> dict[str, Any]:
        """Navigate to a Zillow property page and extract details."""
        url = _PROPERTY_URL.format(address=quote_plus(address))
        try:
            async with self.page(url) as page:
                await page.wait_for_load_state("networkidle", timeout=20000)
                html = await page.content()
            return _parse_property_page(html)
        except Exception as exc:
            logger.warning("Zillow property page error for %s: %s", address, exc)
            return {}
