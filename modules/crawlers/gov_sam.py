"""
gov_sam.py — SAM.gov federal contractor entity registration search.

Queries the SAM.gov Entity Information API for federal contractor and vendor
records by legal business name. Requires a SAM.gov API key configured as
settings.sam_api_key. Returns entity registration status, UEI, and core data.

Registered as "gov_sam".
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from shared.config import settings
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SAM_URL = (
    "https://api.sam.gov/entity-information/v3/entities"
    "?api_key={key}&legalBusinessName={name}"
    "&includeSections=entityRegistration,coreData"
    "&page=0&size=10"
)


def _parse_entities(data: dict) -> list[dict[str, Any]]:
    """Extract entity registration fields from SAM API response."""
    entities: list[dict[str, Any]] = []
    for item in data.get("entityData", [])[:10]:
        if not isinstance(item, dict):
            continue
        reg = item.get("entityRegistration", {})
        core = item.get("coreData", {})
        entity_info = core.get("entityInformation", {})
        entities.append(
            {
                "ueiSAM": reg.get("ueiSAM"),
                "legalBusinessName": reg.get("legalBusinessName"),
                "registrationStatus": reg.get("registrationStatus"),
                "expirationDate": reg.get("registrationExpirationDate"),
                "purposeOfRegistration": reg.get("purposeOfRegistrationDesc"),
                "entityType": reg.get("entityTypeDesc"),
                "congressionalDistrict": reg.get("congressionalDistrict"),
                "fiscalYearEndCloseDate": entity_info.get(
                    "fiscalYearEndCloseDate"
                ),
                "submissionDate": reg.get("submissionDate"),
            }
        )
    return entities


@register("gov_sam")
class SamCrawler(HttpxCrawler):
    """
    Searches SAM.gov for federal contractor entity registration records.

    Requires settings.sam_api_key to be configured. Returns not_configured
    error when no key is present.

    identifier: company or entity legal business name

    Data keys returned:
        entities    — list of entity records (up to 10)
        total_count — total records reported by the API
    """

    platform = "gov_sam"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key: str = getattr(settings, "sam_api_key", "")

        if not api_key:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="not_configured",
                source_reliability=self.source_reliability,
            )

        query = identifier.strip()
        encoded = quote_plus(query)

        url = _SAM_URL.format(key=api_key, name=encoded)
        resp = await self.get(url)

        if resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if resp.status_code == 403:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_api_key",
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
            entities = _parse_entities(payload)
            total_count: int = payload.get("totalRecords", len(entities))
        except Exception as exc:
            logger.warning("SAM.gov JSON parse error: %s", exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="parse_error",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=len(entities) > 0,
            entities=entities,
            total_count=total_count,
        )
