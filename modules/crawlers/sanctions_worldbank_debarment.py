"""
sanctions_worldbank_debarment.py — World Bank debarment/sanctions list search.

Queries the World Bank debarment API for firms and individuals that have been
sanctioned or debarred from World Bank Group financed projects.
Registered as "sanctions_worldbank_debarment".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://apigwext.worldbank.org/dvsvc/v1.0/json/CONTRACT_AWARD/debarred/FIRM_NAME/{name}/0/20"
)


def _word_overlap(query: str, candidate: str) -> float:
    """Return fraction of query words found in candidate string."""
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & c_words) / len(q_words)


def _parse_debarred(payload: Any, query: str) -> list[dict[str, Any]]:
    """
    Extract debarred entity records from World Bank API response.
    Applies word-overlap filtering to surface relevant matches.
    """
    entities: list[dict[str, Any]] = []

    # The API may return a list directly or nested under a key
    records: list[Any] = []
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):  # pragma: no branch
        # Try common key names
        for key in ("debarredFirms", "data", "results", "response"):
            if key in payload and isinstance(payload[key], list):
                records = payload[key]
                break
        if not records and "debarredFirm" in payload:
            item = payload["debarredFirm"]
            records = item if isinstance(item, list) else [item]

    for rec in records:
        if not isinstance(rec, dict):
            continue
        firm_name = rec.get("firmName", "") or rec.get("firm_name", "") or rec.get("name", "")
        overlap = _word_overlap(query, firm_name)
        if overlap < 0.3:
            continue  # Skip low-relevance results
        entities.append(
            {
                "firm_name": firm_name,
                "country": (rec.get("country", "") or rec.get("countryName", "")),
                "from_date": (rec.get("fromDate", "") or rec.get("debarmentFromDate", "")),
                "to_date": (rec.get("toDate", "") or rec.get("debarmentToDate", "")),
                "grounds": (rec.get("grounds", "") or rec.get("sanctionType", "")),
                "ineligibility_period": rec.get("ineligibilityPeriod", ""),
            }
        )
    return entities


@register("sanctions_worldbank_debarment")
class SanctionsWorldBankDebarmentCrawler(HttpxCrawler):
    """
    Searches the World Bank debarment list for sanctioned firms/individuals.

    identifier: company or person name (e.g. "Acme Construction Ltd")

    Data keys returned:
        debarred_entities — list of matched debarment records
        total             — count of matched records
    """

    platform = "sanctions_worldbank_debarment"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote(query, safe="")
        url = _SEARCH_URL.format(name=encoded)

        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                debarred_entities=[],
                total=0,
            )

        if resp.status_code == 404:
            # 404 often means no results in this API
            return self._result(
                identifier,
                found=False,
                debarred_entities=[],
                total=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                debarred_entities=[],
                total=0,
            )

        try:
            payload = resp.json()
            debarred_entities = _parse_debarred(payload, query)
        except Exception as exc:
            logger.warning("WorldBank debarment parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                debarred_entities=[],
                total=0,
            )

        return self._result(
            identifier,
            found=len(debarred_entities) > 0,
            debarred_entities=debarred_entities,
            total=len(debarred_entities),
        )
