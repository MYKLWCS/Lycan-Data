"""
gov_osha.py — OSHA establishment inspection search.

Queries the Department of Labor open data API for workplace safety inspection
records by establishment/company name. Falls back to the OSHA IMIS search
endpoint when the primary API returns no data.

Registered as "gov_osha".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_DOL_URL = "https://data.dol.gov/get/inspection/filter_by_name/{encoded_name}/rows/20"
_OSHA_FALLBACK_URL = (
    "https://www.osha.gov/pls/imis/establishment.search?p_logger=1&action=search&p_est={name}"
)


def _parse_dol_inspections(data: Any) -> list[dict[str, Any]]:
    """Extract inspection fields from DOL API response (list or dict wrapper)."""
    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # Some DOL endpoints wrap results in a key
        for key in ("data", "inspections", "results"):  # pragma: no branch
            if key in data and isinstance(data[key], list):
                rows = data[key]
                break
        if not rows:
            rows = [data] if data else []

    inspections: list[dict[str, Any]] = []
    for item in rows[:20]:
        if not isinstance(item, dict):
            continue
        inspections.append(
            {
                "activity_nr": item.get("activity_nr"),
                "establishment_name": item.get("estab_name"),
                "open_date": item.get("open_date"),
                "close_date": item.get("close_date"),
                "violations_count": item.get("nr_violations"),
                "penalty": item.get("total_current_penalty"),
                "city": item.get("city"),
                "state": item.get("state"),
                "naics_code": item.get("naics_code"),
                "insp_type": item.get("insp_type"),
            }
        )
    return inspections


@register("gov_osha")
class OshaCrawler(HttpxCrawler):
    """
    Searches OSHA inspection records for a given establishment or company name.

    identifier: company or establishment name

    Data keys returned:
        inspections     — list of inspection records (up to 20)
        source          — which endpoint returned data ("dol_api" or "fallback")
    """

    platform = "gov_osha"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        primary_url = _DOL_URL.format(encoded_name=encoded)
        resp = await self.get(primary_url)

        inspections: list[dict[str, Any]] = []
        source = "dol_api"

        if resp is not None and resp.status_code == 200:
            try:
                payload = resp.json()
                inspections = _parse_dol_inspections(payload)
            except Exception as exc:
                logger.warning("OSHA DOL JSON parse error: %s", exc)

        # Fallback: OSHA IMIS endpoint (HTML, but we record the attempt)
        if not inspections:
            source = "fallback"
            fallback_url = _OSHA_FALLBACK_URL.format(name=encoded)
            fb_resp = await self.get(fallback_url)
            if fb_resp is None:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="http_error",
                    source_reliability=self.source_reliability,
                )
            if fb_resp.status_code not in (200, 302):
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error=f"http_{fb_resp.status_code}",
                    source_reliability=self.source_reliability,
                )
            # IMIS returns HTML; we note that the page was reached but parsing
            # is out of scope — return found=True with empty list to signal
            # the caller should follow the URL manually if needed.

        return self._result(
            identifier,
            found=len(inspections) > 0,
            inspections=inspections,
            source=source,
        )
