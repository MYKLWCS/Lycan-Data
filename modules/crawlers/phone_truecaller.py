from __future__ import annotations

import logging
import re

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.phone_carrier import parse_phone_parts
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import LineType
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

# Truecaller line type mapping (their internal type codes)
_TC_LINE_TYPE: dict[str | int, str] = {
    "MOBILE": LineType.MOBILE.value,
    "FIXED_LINE": LineType.LANDLINE.value,
    "FIXED_LINE_OR_MOBILE": LineType.MOBILE.value,
    "VOIP": LineType.VOIP.value,
    "TOLL_FREE": LineType.TOLL_FREE.value,
    0: LineType.MOBILE.value,
    1: LineType.LANDLINE.value,
    2: LineType.MOBILE.value,
    3: LineType.VOIP.value,
    4: LineType.UNKNOWN.value,
}

_TC_BASE = "https://search5-noneu.truecaller.com/v2/search"
_TC_HEADERS = {
    "Authorization": "Bearer null",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; LycanBot/1.0)",
}


@register("phone_truecaller")
class TruecallerCrawler(HttpxCrawler):
    """Enriches a phone number via Truecaller's public search endpoint."""

    platform = "phone_truecaller"
    source_reliability = 0.70
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = parse_phone_parts(identifier)
        country_code = parts["country_code"] if parts["country_code"] != "INTL" else "US"

        # Truecaller expects the number without the leading +
        query_number = re.sub(r"\D", "", parts["e164"])

        url = (
            f"{_TC_BASE}?q={query_number}&countryCode={country_code}&type=4&locAddr=&encoding=json"
        )

        response = await self.get(url, headers=_TC_HEADERS)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 404:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="not_found",
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
            payload = response.json()
        except Exception as exc:
            logger.warning("Truecaller JSON parse failed for %s: %s", identifier, exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="json_parse_error",
                source_reliability=self.source_reliability,
            )

        data = self._parse_payload(payload)

        if not data:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_data",
                source_reliability=self.source_reliability,
            )

        return self._result(identifier, found=True, **data)

    def _parse_payload(self, payload: dict) -> dict | None:
        """Extract name, carrier, score, tags, line_type from Truecaller JSON."""
        try:
            data_list = payload.get("data", [])
            if not data_list:
                return None

            record = data_list[0]
            name = record.get("name", "")

            phones = record.get("phones", [])
            carrier = ""
            raw_type = None
            if phones:
                carrier = phones[0].get("carrier", "")
                raw_type = phones[0].get("type")

            score = record.get("score", 0.0)
            tags = [
                t.get("tag", t) if isinstance(t, dict) else str(t) for t in record.get("tags", [])
            ]

            line_type = _TC_LINE_TYPE.get(raw_type, LineType.UNKNOWN.value)
            if isinstance(raw_type, str):
                line_type = _TC_LINE_TYPE.get(raw_type.upper(), LineType.UNKNOWN.value)

            return {
                "name": name,
                "carrier": carrier,
                "score": score,
                "tags": tags,
                "line_type": line_type,
            }

        except (KeyError, IndexError, TypeError) as exc:
            logger.debug("Truecaller payload parse error: %s", exc)
            return None
