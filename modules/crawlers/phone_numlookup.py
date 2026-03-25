"""
phone_numlookup.py — NumLookupAPI phone number intelligence crawler.

Queries api.numlookupapi.com for carrier, country, validity, and formatting
data on a given phone number. Uses an API key from settings when available;
falls back to the keyless free-tier endpoint.
Registered as "phone_numlookup".
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_NUMLOOKUP_BASE = "https://api.numlookupapi.com/v1/info/{number}"
_NUMLOOKUP_BASE_KEY = "https://api.numlookupapi.com/v1/info/{number}?apikey={key}"


@register("phone_numlookup")
class PhoneNumLookupCrawler(HttpxCrawler):
    """
    Retrieves carrier, country, type, and validity information for a phone number
    via the NumLookupAPI service.

    Reads numlookup_api_key from settings; if absent, uses the keyless free-tier
    URL which may succeed for basic queries or return a 401.
    source_reliability is 0.75 — commercially aggregated carrier data.
    """

    platform = "phone_numlookup"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.75
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        number = identifier.strip()
        api_key = getattr(settings, "numlookup_api_key", "")

        if api_key:
            url = _NUMLOOKUP_BASE_KEY.format(number=number, key=api_key)
        else:
            url = _NUMLOOKUP_BASE.format(number=number)

        response = await self.get(url)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 401:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="unauthorized_no_api_key",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        valid = json_data.get("valid", False)
        found = valid is True

        data = {
            "number_type": json_data.get("number_type"),
            "carrier": json_data.get("carrier"),
            "country_code": json_data.get("country_code"),
            "country_name": json_data.get("country_name"),
            "valid": valid,
            "formatted": json_data.get("formatted"),
        }

        return self._result(identifier, found=found, **data)
