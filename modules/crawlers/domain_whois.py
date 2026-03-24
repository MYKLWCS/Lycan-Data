"""
domain_whois.py — WHOIS scraper via whois.com.

Scrapes https://www.whois.com/whois/{domain} to extract registrar info,
creation/expiry dates, registrant details, and name servers.
Registered as "domain_whois".
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_WHOIS_URL = "https://www.whois.com/whois/{domain}"

# Regex patterns for key WHOIS fields
_PATTERNS: dict[str, str] = {
    "registrar": r"Registrar:\s*(.+)",
    "creation_date": r"Creation Date:\s*(.+)",
    "expiry_date": r"Registry Expiry Date:\s*(.+)",
    "registrant_name": r"Registrant Name:\s*(.+)",
    "registrant_org": r"Registrant Organization:\s*(.+)",
    "registrant_country": r"Registrant Country:\s*(.+)",
}
_NAMESERVER_PATTERN = re.compile(r"Name Server:\s*(.+)", re.IGNORECASE)


def _extract_whois_text(html: str) -> str:
    """Pull raw WHOIS text from whois.com HTML response."""
    soup = BeautifulSoup(html, "html.parser")

    # Primary: look for .df-value spans (whois.com structured layout)
    df_values = soup.select(".df-value")
    if df_values:
        return "\n".join(el.get_text(separator="\n") for el in df_values)

    # Fallback: grab <pre> blocks which contain raw WHOIS dumps
    pre_blocks = soup.find_all("pre")
    if pre_blocks:
        return "\n".join(el.get_text() for el in pre_blocks)

    return soup.get_text(separator="\n")


def _parse_whois(text: str) -> dict:
    """Extract structured fields from raw WHOIS text."""
    result: dict = {}

    for field, pattern in _PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        result[field] = match.group(1).strip() if match else None

    # Collect all name server entries
    result["name_servers"] = [
        m.group(1).strip().lower() for m in _NAMESERVER_PATTERN.finditer(text)
    ]

    return result


@register("domain_whois")
class DomainWhoisCrawler(HttpxCrawler):
    """
    Scrapes whois.com for WHOIS registration data on a target domain.

    Routes through TOR2 — WHOIS lookups can fingerprint investigators.
    """

    platform = "domain_whois"
    source_reliability = 0.75
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        domain = identifier.strip().lower()
        url = _WHOIS_URL.format(domain=domain)

        response = await self.get(url)

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

        whois_text = _extract_whois_text(response.text)
        parsed = _parse_whois(whois_text)

        # If nothing was extracted at all the domain is likely unregistered
        has_data = any(
            v for k, v in parsed.items() if k != "name_servers" and v is not None
        ) or parsed.get("name_servers")

        return self._result(
            identifier,
            found=bool(has_data),
            domain=domain,
            registrar=parsed.get("registrar"),
            creation_date=parsed.get("creation_date"),
            expiry_date=parsed.get("expiry_date"),
            registrant_name=parsed.get("registrant_name"),
            registrant_org=parsed.get("registrant_org"),
            registrant_country=parsed.get("registrant_country"),
            name_servers=parsed.get("name_servers", []),
        )
