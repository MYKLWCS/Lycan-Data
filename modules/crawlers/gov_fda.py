"""
gov_fda.py — FDA drug event and enforcement (recall) search.

Searches the FDA open API for adverse drug events by generic name and
enforcement/recall actions by recalling firm name.

Registered as "gov_fda".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_BASE = "https://api.fda.gov"
_EVENTS_URL = (
    _BASE + "/drug/event.json" + "?search=patient.drug.openfda.generic_name:{query}&limit=5"
)
_ENFORCEMENT_URL = _BASE + "/drug/enforcement.json" + "?search=recalling_firm:{query}&limit=5"


def _parse_events(data: dict) -> list[dict[str, Any]]:
    """Extract key fields from each adverse event report."""
    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        patient = item.get("patient", {})
        drugs = patient.get("drug", [])
        drug_names = [
            d.get("openfda", {}).get("generic_name", [""])[0]
            if d.get("openfda", {}).get("generic_name")
            else d.get("medicinalproduct", "")
            for d in drugs[:5]
        ]
        results.append(
            {
                "report_id": item.get("safetyreportid"),
                "receive_date": item.get("receivedate"),
                "serious": item.get("serious"),
                "drugs": drug_names,
                "reactions": [
                    r.get("reactionmeddrapt", "") for r in patient.get("reaction", [])[:5]
                ],
            }
        )
    return results


def _parse_recalls(data: dict) -> list[dict[str, Any]]:
    """Extract key fields from each enforcement/recall record."""
    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        results.append(
            {
                "recall_number": item.get("recall_number"),
                "recalling_firm": item.get("recalling_firm"),
                "product_description": item.get("product_description"),
                "reason_for_recall": item.get("reason_for_recall"),
                "classification": item.get("classification"),
                "status": item.get("status"),
                "recall_initiation_date": item.get("recall_initiation_date"),
                "state": item.get("state"),
            }
        )
    return results


@register("gov_fda")
class FdaCrawler(HttpxCrawler):
    """
    Queries the FDA open API for adverse drug events and enforcement recalls.

    identifier: drug generic name or recalling company name

    Data keys returned:
        adverse_events  — list of adverse event reports (up to 5)
        recalls         — list of enforcement/recall records (up to 5)
    """

    platform = "gov_fda"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(f'"{query}"')

        events_url = _EVENTS_URL.format(query=encoded)
        recalls_url = _ENFORCEMENT_URL.format(query=encoded)

        events_resp = await self.get(events_url)
        recalls_resp = await self.get(recalls_url)

        if events_resp is None and recalls_resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        adverse_events: list[dict[str, Any]] = []
        recalls: list[dict[str, Any]] = []

        if events_resp is not None and events_resp.status_code == 200:
            try:
                adverse_events = _parse_events(events_resp.json())
            except Exception as exc:
                logger.warning("FDA events JSON parse error: %s", exc)

        if recalls_resp is not None and recalls_resp.status_code == 200:
            try:
                recalls = _parse_recalls(recalls_resp.json())
            except Exception as exc:
                logger.warning("FDA recalls JSON parse error: %s", exc)

        found = len(adverse_events) > 0 or len(recalls) > 0

        return self._result(
            identifier,
            found=found,
            adverse_events=adverse_events,
            recalls=recalls,
        )
