"""
marine_vessel.py — Marine vessel registry and AIS tracking search.

Searches vessel registries and live AIS data from:
1. MarineTraffic public vessel search
2. VesselFinder public search
3. USCG National Vessel Documentation Center (NVDC)
4. IMO GISIS (Global Integrated Shipping Information System)

Can search by vessel name or by owner name to find associated vessels.

Registered as "marine_vessel".
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

# MarineTraffic public search (returns JSON from their internal API)
_MARINETRAFFIC_SEARCH = "https://www.marinetraffic.com/en/ais/index/search/all/keyword:{keyword}"
_MARINETRAFFIC_API = "https://www.marinetraffic.com/getData/get_data_json_4/z:10/X:0/Y:0/station:0"

# VesselFinder public search page
_VESSELFINDER_SEARCH = "https://www.vesselfinder.com/vessels?name={query}&type=0&flag=0&mmsi=&imo="

# USCG NVDC online documentation lookup
_USCG_NVDC_SEARCH = (
    "https://www.nvdc.uscg.mil/uscg.aspx"
    "?Link=http://www.nvdc.uscg.mil/names.aspx&HIN=&DocumentNumber="
    "&VesselName={query}&Owner={owner_query}&State=0&Submit=Search"
)

# IMO GISIS company/vessel search (public)
_IMO_GISIS_SEARCH = "https://gisis.imo.org/Public/MSD/Default.aspx"

# Rough vessel value estimates by type and tonnage (USD)
_VALUE_ESTIMATES = {
    "tanker": 50_000_000,
    "bulk carrier": 30_000_000,
    "container": 80_000_000,
    "cargo": 20_000_000,
    "yacht": 5_000_000,
    "fishing": 2_000_000,
    "passenger": 100_000_000,
    "tug": 5_000_000,
    "default": 10_000_000,
}


def _estimate_value(vessel_type: str, gross_tonnage: Any) -> int:
    """Rough vessel value estimate in USD based on type and tonnage."""
    vtype = (vessel_type or "").lower()
    base = _VALUE_ESTIMATES.get("default", 10_000_000)
    for key, val in _VALUE_ESTIMATES.items():
        if key in vtype:
            base = val
            break
    try:
        gt = int(gross_tonnage or 0)
        if gt > 50000:
            base = int(base * 2.5)
        elif gt > 10000:
            base = int(base * 1.5)
    except (ValueError, TypeError):
        pass
    return base


def _is_vessel_search(identifier: str) -> bool:
    """Return True if identifier is a vessel name (prefixed with 'vessel:')."""
    return identifier.lower().startswith("vessel:")


def _extract_vessel_name(identifier: str) -> str:
    if _is_vessel_search(identifier):
        return identifier[7:].strip()
    return identifier.strip()


def _parse_marinetraffic_html(html: str) -> list[dict[str, Any]]:
    """
    Parse MarineTraffic search results page.
    MarineTraffic renders vessel cards or a table with MMSI, vessel name,
    flag, vessel type.
    """
    vessels: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD or embedded JSON data first
        for script in soup.find_all("script"):
            text = script.string or ""
            if '"mmsi"' in text or '"MMSI"' in text:
                try:
                    import json

                    # Attempt to extract JSON array from script
                    match = re.search(r"\[(\{[^;]+)\]", text, re.DOTALL)
                    if match:
                        data = json.loads(f"[{match.group(1)}]")
                        for item in data[:20]:
                            if isinstance(item, dict):
                                vessels.append(_normalise_mt_item(item))
                except Exception:
                    pass
                break

        # Fallback: table rows
        if not vessels:
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if len(rows) < 2:
                    continue
                headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
                ht = " ".join(headers)
                if not any(kw in ht for kw in ("vessel", "mmsi", "imo", "flag", "name")):
                    continue
                for row in rows[1:]:
                    cells = row.find_all("td")
                    record = {
                        headers[i] if i < len(headers) else f"col_{i}": c.get_text(strip=True)
                        for i, c in enumerate(cells)
                    }
                    name = record.get("vessel name") or record.get("name", "")
                    if not name:
                        continue
                    mmsi = record.get("mmsi", "")
                    imo = record.get("imo", "")
                    flag = record.get("flag") or record.get("country", "")
                    vtype = record.get("vessel type") or record.get("type", "")
                    vessels.append(
                        {
                            "mmsi": mmsi,
                            "imo_number": imo,
                            "vessel_name": name,
                            "call_sign": record.get("callsign", ""),
                            "flag_country": flag,
                            "vessel_type": vtype,
                            "gross_tonnage": record.get("gt") or record.get("gross tonnage", ""),
                            "length_meters": record.get("length", ""),
                            "year_built": record.get("year built") or record.get("built", ""),
                            "owner_name": record.get("owner", ""),
                            "operator_name": record.get("operator", ""),
                            "port_of_registry": record.get("port", ""),
                            "last_port": record.get("last port", ""),
                            "last_seen_lat": None,
                            "last_seen_lon": None,
                            "last_seen_at": record.get("last seen", ""),
                            "is_active": True,
                            "estimated_value_usd": _estimate_value(vtype, record.get("gt")),
                            "source": "marinetraffic",
                        }
                    )
    except Exception as exc:
        logger.debug("MarineTraffic HTML parse error: %s", exc)
    return vessels


def _normalise_mt_item(item: dict) -> dict[str, Any]:
    """Normalise a MarineTraffic JSON vessel object."""
    vtype = item.get("TYPE_NAME") or item.get("VESSEL_TYPE") or item.get("type", "")
    gt = item.get("GT") or item.get("GROSS_TONNAGE") or item.get("gross_tonnage")
    return {
        "mmsi": str(item.get("MMSI") or item.get("mmsi", "")),
        "imo_number": str(item.get("IMO") or item.get("imo", "")),
        "vessel_name": item.get("SHIPNAME") or item.get("vessel_name") or item.get("name", ""),
        "call_sign": item.get("CALLSIGN") or item.get("call_sign", ""),
        "flag_country": item.get("FLAG") or item.get("flag", ""),
        "vessel_type": vtype,
        "gross_tonnage": gt,
        "length_meters": item.get("LENGTH") or item.get("length"),
        "year_built": item.get("YEAR_BUILT") or item.get("year_built"),
        "owner_name": item.get("OWNER") or item.get("owner_name", ""),
        "operator_name": item.get("MANAGER") or item.get("operator_name", ""),
        "port_of_registry": item.get("PORT") or item.get("port_of_registry", ""),
        "last_port": item.get("LAST_PORT") or item.get("last_port", ""),
        "last_seen_lat": item.get("LAT") or item.get("lat"),
        "last_seen_lon": item.get("LON") or item.get("lon"),
        "last_seen_at": item.get("TIMESTAMP") or item.get("last_seen_at", ""),
        "is_active": True,
        "estimated_value_usd": _estimate_value(vtype, gt),
        "source": "marinetraffic",
    }


def _parse_vesselfinder_html(html: str) -> list[dict[str, Any]]:
    """Parse VesselFinder vessel search results page."""
    vessels: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # VesselFinder renders results in a table with class 'ships'
        table = soup.find("table", class_=re.compile("ships|result|vessel"))
        if not table:
            table = soup.find("table")
        if not table:
            return vessels
        rows = table.find_all("tr")
        if len(rows) < 2:
            return vessels
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        for row in rows[1:]:
            cells = row.find_all("td")
            record = {
                headers[i] if i < len(headers) else f"col_{i}": c.get_text(strip=True)
                for i, c in enumerate(cells)
            }
            name = record.get("vessel name") or record.get("name", "")
            if not name:
                continue
            mmsi = record.get("mmsi", "")
            imo = record.get("imo", "")
            flag = record.get("flag") or record.get("country", "")
            vtype = record.get("type") or record.get("vessel type", "")
            vessels.append(
                {
                    "mmsi": mmsi,
                    "imo_number": imo,
                    "vessel_name": name,
                    "call_sign": "",
                    "flag_country": flag,
                    "vessel_type": vtype,
                    "gross_tonnage": record.get("gt", ""),
                    "length_meters": record.get("length", ""),
                    "year_built": record.get("year", ""),
                    "owner_name": "",
                    "operator_name": "",
                    "port_of_registry": "",
                    "last_port": record.get("destination", ""),
                    "last_seen_lat": None,
                    "last_seen_lon": None,
                    "last_seen_at": record.get("last seen", ""),
                    "is_active": True,
                    "estimated_value_usd": _estimate_value(vtype, record.get("gt")),
                    "source": "vesselfinder",
                }
            )
    except Exception as exc:
        logger.debug("VesselFinder HTML parse error: %s", exc)
    return vessels


def _parse_uscg_html(html: str) -> list[dict[str, Any]]:
    """Parse USCG NVDC documentation search results."""
    vessels: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            ht = " ".join(headers)
            if not any(kw in ht for kw in ("vessel", "document", "owner", "name")):
                continue
            for row in rows[1:]:
                cells = row.find_all("td")
                record = {
                    headers[i] if i < len(headers) else f"col_{i}": c.get_text(strip=True)
                    for i, c in enumerate(cells)
                }
                name = record.get("vessel name") or record.get("name", "")
                doc_number = record.get("document number") or record.get("doc #", "")
                if not name and not doc_number:
                    continue
                vessels.append(
                    {
                        "mmsi": "",
                        "imo_number": "",
                        "vessel_name": name,
                        "call_sign": record.get("call sign", ""),
                        "flag_country": "US",
                        "vessel_type": record.get("vessel type") or record.get("type", ""),
                        "gross_tonnage": record.get("gross tons", ""),
                        "length_meters": "",
                        "year_built": "",
                        "owner_name": record.get("owner", ""),
                        "operator_name": "",
                        "port_of_registry": record.get("hailing port", ""),
                        "last_port": "",
                        "last_seen_lat": None,
                        "last_seen_lon": None,
                        "last_seen_at": "",
                        "is_active": True,
                        "estimated_value_usd": _estimate_value(
                            record.get("vessel type", ""), record.get("gross tons")
                        ),
                        "source": "uscg_nvdc",
                        "document_number": doc_number,
                    }
                )
            if vessels:
                break
    except Exception as exc:
        logger.debug("USCG NVDC HTML parse error: %s", exc)
    return vessels


@register("marine_vessel")
class MarineVesselCrawler(HttpxCrawler):
    """
    Searches marine vessel registries and AIS tracking databases.

    When identifier starts with "vessel:" it searches by vessel name.
    Otherwise it searches by owner name across all sources.

    identifier: "vessel:OCEAN QUEEN" for vessel name search,
                or "John Smith" for owner name search

    Data keys returned:
        vessels      — list of {mmsi, imo_number, vessel_name, call_sign,
                       flag_country, vessel_type, gross_tonnage, length_meters,
                       year_built, owner_name, operator_name, port_of_registry,
                       last_port, last_seen_lat, last_seen_lon, last_seen_at,
                       is_active, estimated_value_usd, source}
        vessel_count — integer
        search_type  — "vessel_name" | "owner_name"
        query        — normalised search query
    """

    platform = "marine_vessel"
    category = CrawlerCategory.VEHICLE
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.88
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        if _is_vessel_search(identifier):
            query = _extract_vessel_name(identifier)
            search_type = "vessel_name"
        else:
            query = identifier.strip()
            search_type = "owner_name"

        encoded = quote_plus(query)
        all_vessels: list[dict[str, Any]] = []

        mt_vessels = await self._search_marinetraffic(encoded)
        all_vessels.extend(mt_vessels)

        vf_vessels = await self._search_vesselfinder(encoded)
        all_vessels.extend(vf_vessels)

        uscg_vessels = await self._search_uscg(encoded, search_type)
        all_vessels.extend(uscg_vessels)

        # De-duplicate by (vessel_name, mmsi) where possible
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for v in all_vessels:
            key = (
                f"{v.get('vessel_name', '').lower()}|{v.get('mmsi', '')}|{v.get('imo_number', '')}"
            )
            if key not in seen:
                seen.add(key)
                deduped.append(v)

        return self._result(
            identifier,
            found=len(deduped) > 0,
            vessels=deduped,
            vessel_count=len(deduped),
            search_type=search_type,
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_marinetraffic(self, encoded: str) -> list[dict[str, Any]]:
        url = _MARINETRAFFIC_SEARCH.format(keyword=encoded)
        resp = await self.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.marinetraffic.com/",
            },
        )
        if resp is None or resp.status_code not in (200, 206):
            logger.debug("MarineTraffic returned %s", resp.status_code if resp else "None")
            return []
        return _parse_marinetraffic_html(resp.text)

    async def _search_vesselfinder(self, encoded: str) -> list[dict[str, Any]]:
        url = _VESSELFINDER_SEARCH.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code not in (200, 206):
            return []
        return _parse_vesselfinder_html(resp.text)

    async def _search_uscg(self, encoded: str, search_type: str) -> list[dict[str, Any]]:
        if search_type == "vessel_name":
            url = _USCG_NVDC_SEARCH.format(query=encoded, owner_query="")
        else:
            url = _USCG_NVDC_SEARCH.format(query="", owner_query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code not in (200, 206):
            return []
        return _parse_uscg_html(resp.text)
