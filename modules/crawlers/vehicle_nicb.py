"""
vehicle_nicb.py — NICB VINCheck stolen/salvage vehicle lookup.

Submits a 17-character VIN to the NICB VINCheck service and returns
is_stolen, is_salvage, and is_total_loss flags.

Registered as "vehicle_nicb".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_API_URL = "https://www.nicb.org/api/vincheck?vin={vin}"
_FORM_URL = "https://www.nicb.org/vincheck/results?vin={vin}"
_HEADERS = {
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.nicb.org/vincheck",
}

# Valid VIN characters: 0-9, A-Z except I, O, Q
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# VIN validation
# ---------------------------------------------------------------------------


def _valid_vin(vin: str) -> bool:
    """Return True if vin is a syntactically valid 17-char VIN (no I/O/Q)."""
    return bool(_VIN_RE.match(vin))


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _parse_json_response(data: dict) -> dict[str, Any]:
    """Parse NICB JSON API response."""
    result: dict[str, Any] = {
        "is_stolen": False,
        "is_salvage": False,
        "is_total_loss": False,
        "message": "",
    }
    # Common NICB API field names — adapt if schema changes
    result["is_stolen"] = bool(
        data.get("stolen") or data.get("isStolen") or data.get("theft_records")
    )
    result["is_salvage"] = bool(
        data.get("salvage") or data.get("isSalvage") or data.get("salvage_records")
    )
    result["is_total_loss"] = bool(
        data.get("total_loss") or data.get("isTotalLoss") or data.get("total_loss_records")
    )
    result["message"] = data.get("message") or data.get("description") or data.get("status", "")
    return result


def _parse_html_response(html: str) -> dict[str, Any]:
    """Fallback: parse NICB VINCheck HTML results page."""
    result: dict[str, Any] = {
        "is_stolen": False,
        "is_salvage": False,
        "is_total_loss": False,
        "message": "",
    }
    text_lower = html.lower()
    if "stolen" in text_lower:
        result["is_stolen"] = True
    if "salvage" in text_lower:
        result["is_salvage"] = True
    if "total loss" in text_lower or "total_loss" in text_lower:
        result["is_total_loss"] = True

    # Attempt to extract a message paragraph
    m = re.search(
        r'<p[^>]*class="[^"]*(?:message|result|status)[^"]*"[^>]*>(.*?)</p>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        raw = re.sub(r"<[^>]+>", " ", m.group(1)).strip()
        result["message"] = " ".join(raw.split())

    return result


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("vehicle_nicb")
class VehicleNicbCrawler(HttpxCrawler):
    """
    Checks a VIN against the NICB VINCheck database for theft and salvage records.

    identifier: 17-character VIN (alphanumeric, no I/O/Q).

    Returns:
        vin            — normalised VIN
        is_stolen      — True if theft record found
        is_salvage     — True if salvage record found
        is_total_loss  — True if total loss record found
        message        — status message from NICB

    source_reliability: 0.90 — NICB is the authoritative US vehicle crime database.
    """

    platform = "vehicle_nicb"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        vin = identifier.strip().upper()

        if not _valid_vin(vin):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_vin_format",
                source_reliability=self.source_reliability,
            )

        # Try JSON API first
        api_url = _API_URL.format(vin=vin)
        response = await self.get(api_url, headers=_HEADERS)

        flags: dict[str, Any] | None = None

        if response is not None and response.status_code == 200:
            try:
                json_data = response.json()
                flags = _parse_json_response(json_data)
            except Exception:
                # JSON parse failed — fall through to HTML
                flags = None

        # Fallback: POST/GET the form-based results page
        if flags is None:
            form_url = _FORM_URL.format(vin=vin)
            html_response = await self.post(
                form_url,
                data={"vin": vin},
                headers={**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            )
            if html_response is None:
                # Also try GET
                html_response = await self.get(form_url, headers=_HEADERS)

            if html_response is None:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="http_error",
                    source_reliability=self.source_reliability,
                )

            if html_response.status_code == 429:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="rate_limited",
                    source_reliability=self.source_reliability,
                )

            if html_response.status_code != 200:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error=f"http_{html_response.status_code}",
                    source_reliability=self.source_reliability,
                )

            flags = _parse_html_response(html_response.text)

        found = flags.get("is_stolen") or flags.get("is_salvage") or flags.get("is_total_loss")

        return self._result(
            identifier,
            found=bool(found),
            vin=vin,
            is_stolen=flags["is_stolen"],
            is_salvage=flags["is_salvage"],
            is_total_loss=flags["is_total_loss"],
            message=flags["message"],
        )
