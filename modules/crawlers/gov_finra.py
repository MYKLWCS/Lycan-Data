"""
gov_finra.py — FINRA BrokerCheck individual broker/advisor search.

Queries the FINRA BrokerCheck public API for registered broker and investment
advisor records by full name, returning registration scope and disclosure flags.

Registered as "gov_finra".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_FINRA_URL = (
    "https://api.brokercheck.finra.org/search/individual"
    "?query={name}&hl=true&includePrevious=true&nRows=10&start=0&wantCounts=false"
)
_FINRA_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://brokercheck.finra.org/",
}


def _parse_brokers(data: dict) -> list[dict[str, Any]]:
    """Extract broker fields from BrokerCheck search response."""
    brokers: list[dict[str, Any]] = []
    hits = data.get("hits", {})
    if isinstance(hits, dict):
        hit_list = hits.get("hits", [])
    else:
        hit_list = hits or []

    for item in hit_list[:10]:
        if not isinstance(item, dict):
            continue
        source = item.get("_source", item)
        brokers.append(
            {
                "ind_source_id": source.get("ind_source_id"),
                "ind_firstname": source.get("ind_firstname"),
                "ind_lastname": source.get("ind_lastname"),
                "ind_middlename": source.get("ind_middlename"),
                "bc_scope": source.get("bc_scope"),
                "ind_bc_disc_fl": source.get("ind_bc_disc_fl"),
                "ind_ia_disc_fl": source.get("ind_ia_disc_fl"),
                "ind_bc_scope": source.get("ind_bc_scope"),
                "ind_ia_scope": source.get("ind_ia_scope"),
                "ind_industry_cal_yr_cnt": source.get(
                    "ind_industry_cal_yr_cnt"
                ),
            }
        )
    return brokers


@register("gov_finra")
class FinraCrawler(HttpxCrawler):
    """
    Searches FINRA BrokerCheck for broker and investment advisor records.

    identifier: broker or advisor full name (e.g. "John Smith")

    Data keys returned:
        brokers     — list of matching broker records (up to 10)
        total       — total matching records reported by the API
    """

    platform = "gov_finra"
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        url = _FINRA_URL.format(name=encoded)
        resp = await self.get(url, headers=_FINRA_HEADERS)

        if resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if resp.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if resp.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{resp.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            payload = resp.json()
            brokers = _parse_brokers(payload)
            hits_meta = payload.get("hits", {})
            if isinstance(hits_meta, dict):
                total: int = hits_meta.get("total", {}).get(
                    "value", len(brokers)
                ) if isinstance(hits_meta.get("total"), dict) else int(
                    hits_meta.get("total", len(brokers))
                )
            else:
                total = len(brokers)
        except Exception as exc:
            logger.warning("FINRA BrokerCheck JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(brokers) > 0,
            brokers=brokers,
            total=total,
        )
