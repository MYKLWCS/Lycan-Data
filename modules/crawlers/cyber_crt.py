"""
cyber_crt.py — Certificate Transparency Log crawler via crt.sh.

Queries the crt.sh JSON API to enumerate TLS certificates issued for a domain.
Registered as "cyber_crt".
"""
from __future__ import annotations
import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_CRT_URL = "https://crt.sh/?q={identifier}&output=json"
_CRT_HEADERS = {"User-Agent": "Lycan-OSINT/1.0", "Accept": "application/json"}

_KEEP_FIELDS = {"id", "issuer_ca_id", "issuer_name", "name_value", "not_before", "not_after"}


def _parse_certs(raw: list[dict]) -> list[dict]:
    """Trim each certificate entry to the fields we care about."""
    out = []
    for entry in raw:
        out.append({k: entry.get(k) for k in _KEEP_FIELDS})
    return out


@register("cyber_crt")
class CyberCrtCrawler(HttpxCrawler):
    """
    Queries crt.sh for TLS certificates associated with a domain.

    source_reliability is high (0.95) — crt.sh indexes CT logs directly.
    Does not require Tor; crt.sh is a public service.
    """

    platform = "cyber_crt"
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        domain = identifier.strip().lower()
        url = _CRT_URL.format(identifier=domain)

        response = await self.get(url, headers=_CRT_HEADERS)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
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
            raw = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        if not isinstance(raw, list):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="unexpected_response_format",
                source_reliability=self.source_reliability,
            )

        certs = _parse_certs(raw)

        return self._result(
            identifier,
            found=bool(certs),
            certificates=certs[:50],
            count=len(certs),
            domain=domain,
        )
