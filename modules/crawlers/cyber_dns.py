"""
cyber_dns.py — DNS record lookup crawler using stdlib + Google DNS-over-HTTPS.

Performs A, AAAA, MX, TXT, NS lookups and reverse DNS resolution.
SPF/DKIM TXT records are parsed to surface subdomain hints.

No external DNS library required — uses socket + httpx (via self.get).

Registered as "cyber_dns".
"""

from __future__ import annotations

import logging
import re
import socket
from urllib.parse import quote

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_DOH_BASE = "https://dns.google/resolve"
_DOH_HEADERS = {"Accept": "application/dns-json"}

# Regex to extract include: / a: / mx: domains from SPF records
_SPF_INCLUDE_RE = re.compile(r"(?:include:|a:|mx:)([\w.\-]+)", re.IGNORECASE)


def _doh_url(name: str, rtype: str) -> str:
    return f"{_DOH_BASE}?name={quote(name)}&type={rtype}"


def _extract_doh_answers(data: dict, strip_dot: bool = True) -> list[str]:
    """Pull the 'data' field from each answer section entry."""
    values: list[str] = []
    for answer in data.get("Answer", []):
        raw = answer.get("data", "")
        if strip_dot and raw.endswith("."):
            raw = raw[:-1]
        values.append(raw)
    return values


def _spf_subdomain_hints(txt_records: list[str]) -> list[str]:
    """Parse SPF TXT records to surface referenced domains."""
    hints: set[str] = set()
    for record in txt_records:
        if "v=spf1" in record.lower():
            for match in _SPF_INCLUDE_RE.findall(record):
                hints.add(match.lower())
    return sorted(hints)


@register("cyber_dns")
class DnsCrawler(HttpxCrawler):
    """
    Performs DNS lookups for a domain using stdlib socket + Google DoH.

    identifier: domain name (e.g. "example.com")

    Data keys returned:
        a_records, aaaa_records, mx_records, txt_records, ns_records,
        reverse_dns, subdomain_hints
    """

    platform = "cyber_dns"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        domain = identifier.strip().lower()

        a_records = self._resolve_a(domain)
        aaaa_records = self._resolve_aaaa(domain)

        mx_records = await self._doh_lookup(domain, "MX")
        txt_records = await self._doh_lookup(domain, "TXT", strip_dot=False)
        ns_records = await self._doh_lookup(domain, "NS")

        # Reverse DNS for first A record
        reverse_dns = ""
        if a_records:
            reverse_dns = self._reverse_dns(a_records[0])

        subdomain_hints = _spf_subdomain_hints(txt_records)

        found = bool(a_records or aaaa_records or mx_records or ns_records)

        return self._result(
            identifier,
            found=found,
            a_records=a_records,
            aaaa_records=aaaa_records,
            mx_records=mx_records,
            txt_records=txt_records,
            ns_records=ns_records,
            reverse_dns=reverse_dns,
            subdomain_hints=subdomain_hints,
        )

    # ------------------------------------------------------------------
    # Stdlib socket helpers
    # ------------------------------------------------------------------

    def _resolve_a(self, domain: str) -> list[str]:
        try:
            results = socket.getaddrinfo(domain, None, socket.AF_INET)
            return sorted({r[4][0] for r in results})
        except Exception as exc:
            logger.debug("DNS A lookup failed for %s: %s", domain, exc)
            return []

    def _resolve_aaaa(self, domain: str) -> list[str]:
        try:
            results = socket.getaddrinfo(domain, None, socket.AF_INET6)
            return sorted({r[4][0] for r in results})
        except Exception as exc:
            logger.debug("DNS AAAA lookup failed for %s: %s", domain, exc)
            return []

    def _reverse_dns(self, ip: str) -> str:
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except Exception as exc:
            logger.debug("Reverse DNS failed for %s: %s", ip, exc)
            return ""

    # ------------------------------------------------------------------
    # Google DNS-over-HTTPS helper
    # ------------------------------------------------------------------

    async def _doh_lookup(self, domain: str, rtype: str, strip_dot: bool = True) -> list[str]:
        url = _doh_url(domain, rtype)
        resp = await self.get(url, headers=_DOH_HEADERS)

        if resp is None or resp.status_code != 200:
            logger.debug(
                "DoH %s lookup failed for %s (status=%s)",
                rtype,
                domain,
                resp.status_code if resp else "None",
            )
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("DoH JSON parse error for %s %s: %s", rtype, domain, exc)
            return []

        return _extract_doh_answers(data, strip_dot=strip_dot)
