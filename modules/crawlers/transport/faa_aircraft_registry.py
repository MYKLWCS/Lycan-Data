"""
faa_aircraft_registry.py — FAA Aircraft Registry search.

Searches the FAA Releasable Aircraft Registry:
- Bulk CSV download from https://registry.faa.gov/database/ReleasableAircraft.zip
  (cached locally in /tmp/lycan_cache/)
- Live N-number lookup via https://registry.faa.gov/aircraftinquiry/Search/NNumberInquiry

Supports owner name search and direct N-number lookup (prefix "N12345").

Registered as "faa_aircraft_registry".
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
import zipfile
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_FAA_ZIP_URL = "https://registry.faa.gov/database/ReleasableAircraft.zip"
_FAA_NNUMBER_URL = (
    "https://registry.faa.gov/aircraftinquiry/Search/NNumberInquiry?NNumbertxt={nnumber}"
)
_CACHE_DIR = "/tmp/lycan_cache"
_CACHE_ZIP = os.path.join(_CACHE_DIR, "faa_aircraft.zip")
_CACHE_MASTER = os.path.join(_CACHE_DIR, "faa_master.csv")
_CACHE_DEREGISTERED = os.path.join(_CACHE_DIR, "faa_dereg.csv")
_CACHE_MAX_AGE_HOURS = 48.0

# FAA MASTER.txt column names (fixed-width, CSV-in-zip)
# Per FAA: https://registry.faa.gov/database/Help/RD/ReleasableAircraftDownloadHelp.pdf
_MASTER_COLS = [
    "n_number", "serial_number", "mfr_mdl_code", "eng_mfr_mdl",
    "year_mfr", "type_registrant", "name", "street", "street2",
    "city", "state", "zip_code", "region", "county", "country",
    "last_action_date", "cert_issue_date", "certification",
    "type_aircraft", "type_engine", "status_code", "mode_s_code",
    "fract_owner", "air_worth_date", "other_names_1", "other_names_2",
    "other_names_3", "other_names_4", "other_names_5", "expiration_date",
    "unique_id", "kit_mfr", "kit_model", "mode_s_code_hex",
]

_REGISTRANT_TYPES = {
    "1": "Individual",
    "2": "Partnership",
    "3": "Corporation",
    "4": "Co-Owned",
    "5": "Government",
    "7": "LLC",
    "8": "Non-Citizen Corporation",
    "9": "Non-Citizen Co-Owned",
}

_AIRCRAFT_TYPES = {
    "1": "Glider",
    "2": "Balloon",
    "3": "Blimp/Dirigible",
    "4": "Fixed Wing Single Engine",
    "5": "Fixed Wing Multi Engine",
    "6": "Rotorcraft",
    "7": "Weight-Shift Control",
    "8": "Powered Parachute",
    "9": "Gyroplane",
    "H": "Hybrid Lift",
    "O": "Other",
}

_ENGINE_TYPES = {
    "0": "None",
    "1": "Reciprocating",
    "2": "Turbo-Prop",
    "3": "Turbo-Shaft",
    "4": "Turbo-Jet",
    "5": "Turbo-Fan",
    "6": "Ramjet",
    "7": "2 Cycle",
    "8": "4 Cycle",
    "9": "Unknown",
    "10": "Electric",
    "11": "Rotary",
}

# Rough value estimates by aircraft type (USD)
_VALUE_ESTIMATES = {
    "Fixed Wing Single Engine": 150_000,
    "Fixed Wing Multi Engine": 800_000,
    "Rotorcraft": 2_000_000,
    "Turbo-Jet": 15_000_000,
    "Turbo-Fan": 25_000_000,
    "Turbo-Prop": 3_000_000,
    "Glider": 50_000,
    "Balloon": 30_000,
    "default": 200_000,
}


def _cache_valid(path: str, max_age_hours: float = _CACHE_MAX_AGE_HOURS) -> bool:
    if not os.path.exists(path):
        return False
    return (time.time() - os.path.getmtime(path)) / 3600 < max_age_hours


def _word_overlap(query: str, candidate: str) -> float:
    q = set(query.lower().split())
    c = set(candidate.lower().split())
    if not q:
        return 0.0
    return len(q & c) / len(q)


def _is_nnumber(identifier: str) -> bool:
    """Return True if identifier looks like an FAA N-number (N12345)."""
    clean = identifier.strip().upper().lstrip("N")
    return bool(clean) and clean.replace("-", "").isalnum() and len(identifier.strip()) <= 7


def _normalise_nnumber(n: str) -> str:
    """Ensure N-number is uppercase and starts with N."""
    n = n.strip().upper()
    if not n.startswith("N"):
        n = f"N{n}"
    return n


def _row_to_aircraft(row: dict[str, str], is_deregistered: bool = False) -> dict[str, Any]:
    """Convert a FAA master CSV row dict to a normalised aircraft record."""
    n_number = f"N{row.get('n_number', '').strip()}"
    name = row.get("name", "").strip()
    street = row.get("street", "").strip()
    street2 = row.get("street2", "").strip()
    city = row.get("city", "").strip()
    state = row.get("state", "").strip()
    zip_code = row.get("zip_code", "").strip()
    address_parts = [p for p in [street, street2, city, state, zip_code] if p]
    address = ", ".join(address_parts)

    type_code = row.get("type_aircraft", "").strip()
    engine_code = row.get("type_engine", "").strip()
    reg_type_code = row.get("type_registrant", "").strip()
    aircraft_type = _AIRCRAFT_TYPES.get(type_code, type_code)
    engine_type = _ENGINE_TYPES.get(engine_code, engine_code)
    registrant_type = _REGISTRANT_TYPES.get(reg_type_code, reg_type_code)

    cert_date = row.get("cert_issue_date", "").strip()
    exp_date = row.get("expiration_date", "").strip()
    year_mfr = row.get("year_mfr", "").strip()

    # Estimated value: engine type is most predictive
    est_value = _VALUE_ESTIMATES.get(
        engine_type, _VALUE_ESTIMATES.get(aircraft_type, _VALUE_ESTIMATES["default"])
    )

    return {
        "n_number": n_number,
        "serial_number": row.get("serial_number", "").strip(),
        "manufacturer": row.get("kit_mfr", "").strip() or row.get("mfr_mdl_code", "").strip(),
        "model": row.get("kit_model", "").strip(),
        "aircraft_type": aircraft_type,
        "engine_type": engine_type,
        "num_engines": None,
        "num_seats": None,
        "year_manufactured": year_mfr,
        "airworthiness_class": row.get("certification", "").strip(),
        "registration_date": cert_date,
        "expiration_date": exp_date,
        "owner_name": name,
        "registrant_type": registrant_type,
        "registrant_address": address,
        "is_deregistered": is_deregistered,
        "estimated_value_usd": est_value,
        "status_code": row.get("status_code", "").strip(),
    }


def _search_master_csv(csv_text: str, query: str, threshold: float = 0.6) -> list[dict[str, Any]]:
    """Search the FAA master CSV for owner name matches."""
    results: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(csv_text))
    for row_list in reader:
        # FAA master CSV has no header row; columns are positional
        if len(row_list) < 8:
            continue
        # Column 6 (0-indexed) is the registrant name
        owner_name = row_list[6].strip() if len(row_list) > 6 else ""
        if not owner_name:
            continue
        score = _word_overlap(query, owner_name)
        if score < threshold:
            continue
        # Build a dict using known column positions
        row_dict: dict[str, str] = {}
        for i, col_name in enumerate(_MASTER_COLS):
            row_dict[col_name] = row_list[i].strip() if i < len(row_list) else ""
        results.append(_row_to_aircraft(row_dict, is_deregistered=False))
        if len(results) >= 50:
            break
    return results


def _parse_nnumber_html(html: str, n_number: str) -> list[dict[str, Any]]:
    """
    Parse the FAA N-Number inquiry HTML result page.
    Returns a single aircraft record if found.
    """
    results: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # FAA inquiry page has definition lists or tables with label-value pairs
        data: dict[str, str] = {}

        # Try <dt>/<dd> label-value pairs
        dts = soup.find_all("dt")
        for dt in dts:
            label = dt.get_text(strip=True).lower().rstrip(":")
            dd = dt.find_next_sibling("dd")
            if dd:
                data[label] = dd.get_text(strip=True)

        # Try table label-value layout
        if not data:
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all(["th", "td"])
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower().rstrip(":")
                        value = cells[1].get_text(strip=True)
                        data[label] = value

        if not data:
            return results

        owner = (
            data.get("name")
            or data.get("registrant name")
            or data.get("owner")
            or ""
        )
        street = data.get("street", "") or data.get("address", "")
        city = data.get("city", "")
        state = data.get("state", "")
        zip_code = data.get("zip code", "") or data.get("zip", "")
        address_parts = [p for p in [street, city, state, zip_code] if p]
        address = ", ".join(address_parts)

        aircraft_type = data.get("aircraft type", "") or data.get("type", "")
        engine_type = data.get("engine type", "") or data.get("engine", "")
        cert_date = data.get("certification date", "") or data.get("cert issue date", "")
        exp_date = data.get("expiration date", "")
        year_mfr = data.get("year manufactured", "") or data.get("year", "")
        serial = data.get("serial number", "")
        manufacturer = data.get("manufacturer", "") or data.get("mfr", "")
        model = data.get("model", "")

        est_value = _VALUE_ESTIMATES.get(
            engine_type, _VALUE_ESTIMATES.get(aircraft_type, _VALUE_ESTIMATES["default"])
        )

        results.append(
            {
                "n_number": n_number,
                "serial_number": serial,
                "manufacturer": manufacturer,
                "model": model,
                "aircraft_type": aircraft_type,
                "engine_type": engine_type,
                "num_engines": None,
                "num_seats": None,
                "year_manufactured": year_mfr,
                "airworthiness_class": data.get("airworthiness class", ""),
                "registration_date": cert_date,
                "expiration_date": exp_date,
                "owner_name": owner,
                "registrant_type": data.get("type registrant", ""),
                "registrant_address": address,
                "is_deregistered": False,
                "estimated_value_usd": est_value,
                "status_code": data.get("status", ""),
            }
        )
    except Exception as exc:
        logger.debug("FAA N-number HTML parse error: %s", exc)
    return results


@register("faa_aircraft_registry")
class FaaAircraftRegistryCrawler(HttpxCrawler):
    """
    Searches the FAA Aircraft Registry for all aircraft registered to an
    owner (by name) or looks up a specific aircraft by N-number.

    Bulk CSV is downloaded once and cached for 48 hours. N-number lookups
    use the live FAA inquiry portal.

    identifier: person/company name OR N-number "N12345"

    Data keys returned:
        aircraft      — list of {n_number, serial_number, manufacturer, model,
                        aircraft_type, engine_type, num_engines, num_seats,
                        year_manufactured, airworthiness_class, registration_date,
                        expiration_date, owner_name, registrant_type,
                        registrant_address, is_deregistered, estimated_value_usd}
        aircraft_count — integer
        search_type    — "n_number" | "owner_name"
        query          — normalised search query
    """

    platform = "faa_aircraft_registry"
    source_reliability = 0.95
    requires_tor = False
    proxy_tier = "direct"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        if _is_nnumber(query):
            n_number = _normalise_nnumber(query)
            aircraft = await self._lookup_nnumber(n_number)
            return self._result(
                identifier,
                found=len(aircraft) > 0,
                aircraft=aircraft,
                aircraft_count=len(aircraft),
                search_type="n_number",
                query=n_number,
            )

        # Owner name search via bulk CSV
        csv_text = await self._get_master_csv()
        if csv_text is None:
            return self._result(
                identifier,
                found=False,
                error="csv_download_failed",
                aircraft=[],
                aircraft_count=0,
                search_type="owner_name",
                query=query,
            )

        aircraft = _search_master_csv(csv_text, query)
        return self._result(
            identifier,
            found=len(aircraft) > 0,
            aircraft=aircraft,
            aircraft_count=len(aircraft),
            search_type="owner_name",
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_master_csv(self) -> str | None:
        """Return FAA master CSV text from cache or download the bulk ZIP."""
        os.makedirs(_CACHE_DIR, exist_ok=True)

        if _cache_valid(_CACHE_MASTER):
            logger.debug("FAA: using cached master CSV at %s", _CACHE_MASTER)
            try:
                with open(_CACHE_MASTER, encoding="latin-1") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("FAA: cache read failed: %s", exc)

        logger.info("FAA: downloading ReleasableAircraft.zip from %s", _FAA_ZIP_URL)
        resp = await self.get(_FAA_ZIP_URL)
        if resp is None or resp.status_code != 200:
            logger.error(
                "FAA: ZIP download failed (%s)", resp.status_code if resp else "None"
            )
            return None

        try:
            with open(_CACHE_ZIP, "wb") as fh:
                fh.write(resp.content)
            logger.debug("FAA: ZIP saved to %s", _CACHE_ZIP)
        except OSError as exc:
            logger.warning("FAA: could not save ZIP: %s", exc)
            # Try to parse from memory
            try:
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                master_name = next(
                    (n for n in zf.namelist() if "MASTER" in n.upper()), None
                )
                if master_name:
                    text = zf.read(master_name).decode("latin-1", errors="replace")
                    return text
            except Exception as inner_exc:
                logger.error("FAA: in-memory ZIP parse failed: %s", inner_exc)
            return None

        try:
            zf = zipfile.ZipFile(_CACHE_ZIP)
            master_name = next(
                (n for n in zf.namelist() if "MASTER" in n.upper()), None
            )
            if not master_name:
                logger.error("FAA: MASTER.txt not found in ZIP")
                return None
            text = zf.read(master_name).decode("latin-1", errors="replace")
            with open(_CACHE_MASTER, "w", encoding="latin-1", errors="replace") as fh:
                fh.write(text)
            logger.debug("FAA: master CSV extracted and cached at %s", _CACHE_MASTER)
            return text
        except Exception as exc:
            logger.error("FAA: ZIP extraction failed: %s", exc)
            return None

    async def _lookup_nnumber(self, n_number: str) -> list[dict[str, Any]]:
        """Live lookup of a specific N-number via the FAA inquiry portal."""
        n_clean = n_number.lstrip("N").lstrip("n")
        url = _FAA_NNUMBER_URL.format(nnumber=n_clean)
        resp = await self.get(url)
        if resp is None or resp.status_code not in (200, 206):
            logger.debug(
                "FAA N-number inquiry returned %s", resp.status_code if resp else "None"
            )
            return []
        return _parse_nnumber_html(resp.text, n_number)
