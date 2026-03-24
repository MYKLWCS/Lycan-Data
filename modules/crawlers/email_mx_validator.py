"""
email_mx_validator.py — Pure Python MX record lookup and disposable domain check.

Performs DNS MX record resolution (via dnspython with socket fallback) and checks
the domain against a curated list of known disposable/throwaway email providers.
No external HTTP required — all stdlib + optional dnspython.
Registered as "email_mx_validator".
"""
from __future__ import annotations
import logging
import socket

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "guerrillamail.com",
    "tempmail.com",
    "throwaway.email",
    "yopmail.com",
    "10minutemail.com",
    "trashmail.com",
    "sharklasers.com",
    "guerrillamailblock.com",
    "grr.la",
    "guerrillamail.info",
    "spam4.me",
    "byom.de",
    "dispostable.com",
    "spamgourmet.com",
    "mailnull.com",
}


@register("email_mx_validator")
class EmailMXValidatorCrawler(HttpxCrawler):
    """
    Validates an email address by resolving its domain's MX records and checking
    against known disposable email providers.

    Uses dnspython when available; falls back to socket gethostbyname for basic
    domain reachability when dnspython is not installed.
    source_reliability is 0.90 — DNS is authoritative for deliverability.
    """

    platform = "email_mx_validator"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        if "@" not in identifier:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="Not an email address",
                source_reliability=self.source_reliability,
            )

        domain = identifier.split("@")[1].lower()

        try:
            import dns.resolver  # type: ignore[import-untyped]
            answers = dns.resolver.resolve(domain, "MX")
            mx_records = sorted(
                [(r.preference, str(r.exchange)) for r in answers]
            )
            mx_available = True
        except Exception:
            # Fallback: check if domain resolves at all via socket
            try:
                socket.gethostbyname(domain)
                mx_records = []
                mx_available = True
            except socket.gaierror:
                mx_records = []
                mx_available = False

        is_disposable = domain in _DISPOSABLE_DOMAINS
        found = mx_available

        data = {
            "email": identifier,
            "domain": domain,
            "mx_available": mx_available,
            "mx_records": mx_records[:5],
            "is_disposable": is_disposable,
        }

        return self._result(identifier, found=found, **data)
