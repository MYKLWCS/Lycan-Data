"""
domain_theharvester.py — theHarvester subprocess wrapper.

Runs theHarvester to collect emails, subdomains, IPs, and URLs from
passive sources (Bing, DuckDuckGo, crt.sh, etc.) for a given domain.
Registered as "domain_harvester".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid

from modules.crawlers.base import BaseCrawler
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

HARVESTER_TIMEOUT = 120  # seconds


async def _run_harvester(domain: str) -> dict:
    """Run theHarvester subprocess and return parsed JSON output dict."""
    run_id = str(uuid.uuid4())[:8]
    outfile = os.path.join(tempfile.gettempdir(), f"harvest_{run_id}")
    try:
        proc = await asyncio.create_subprocess_exec(
            "theHarvester",
            "-d",
            domain,
            "-b",
            "all",
            "-l",
            "100",
            "-f",
            outfile,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=HARVESTER_TIMEOUT)
        json_path = f"{outfile}.json"
        if os.path.exists(json_path):
            with open(json_path) as f:
                data = json.load(f)
            os.unlink(json_path)
            return data
    except (TimeoutError, FileNotFoundError):
        logger.debug("theHarvester run failed or timed out for %s", domain, exc_info=True)
    return {}


async def _check_harvester_installed() -> bool:
    """Return True if theHarvester is available on PATH."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "theHarvester",
            "--help",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return proc.returncode == 0
    except (TimeoutError, FileNotFoundError):
        return False


def _parse_harvester_output(raw: dict) -> dict:
    """Normalise the JSON structure theHarvester writes to disk."""
    emails = list(raw.get("emails", []) or [])
    # "hosts" field contains subdomains (sometimes as "host:ip" strings)
    raw_hosts = raw.get("hosts", []) or []
    subdomains: list[str] = []
    for h in raw_hosts:
        # Strip trailing IP if present (e.g. "sub.example.com:1.2.3.4")
        subdomains.append(str(h).split(":")[0].strip())
    ips = list(raw.get("ips", []) or [])
    urls = list(raw.get("urls", []) or [])
    return {
        "emails": emails,
        "subdomains": subdomains,
        "ips": ips,
        "urls": urls,
    }


@register("domain_harvester")
class DomainHarvesterCrawler(BaseCrawler):
    """
    Wraps theHarvester CLI to enumerate emails, subdomains, IPs, and URLs
    for a target domain using passive OSINT sources.

    theHarvester manages its own outbound requests so Tor is not required here.
    """

    platform = "domain_harvester"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.70
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        domain = identifier.strip().lower()

        if not await _check_harvester_installed():
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="theharvester_not_installed",
                source_reliability=self.source_reliability,
            )

        try:
            raw = await _run_harvester(domain)
        except TimeoutError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="harvester_timeout",
                source_reliability=self.source_reliability,
            )
        except FileNotFoundError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="theharvester_not_installed",
                source_reliability=self.source_reliability,
            )

        parsed = _parse_harvester_output(raw)

        found = bool(parsed["emails"] or parsed["subdomains"] or parsed["ips"] or parsed["urls"])

        return self._result(
            identifier,
            found=found,
            domain=domain,
            emails=parsed["emails"],
            subdomains=parsed["subdomains"],
            ips=parsed["ips"],
            urls=parsed["urls"],
        )
