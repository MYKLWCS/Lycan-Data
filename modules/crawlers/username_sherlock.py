"""
username_sherlock.py — Sherlock subprocess wrapper.

Searches 300+ sites for a username using the sherlock CLI tool.
Registered as "username_sherlock".
"""

from __future__ import annotations

import asyncio
import logging
import re

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

SHERLOCK_TIMEOUT = 180  # seconds


async def _run_sherlock(username: str) -> list[dict]:
    """Run sherlock, return list of {site, url} dicts."""
    proc = await asyncio.create_subprocess_exec(
        "sherlock",
        username,
        "--print-found",
        "--no-color",
        "--timeout",
        "10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=SHERLOCK_TIMEOUT)
    text = stdout.decode(errors="replace")
    matches = re.findall(r"\[\+\]\s+([^:]+):\s+(https?://\S+)", text)
    return [{"site": m[0].strip(), "url": m[1].strip()} for m in matches]


async def _check_sherlock_installed() -> bool:
    """Return True if sherlock is available on PATH."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sherlock",
            "--help",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return True
    except (TimeoutError, FileNotFoundError):
        return False


@register("username_sherlock")
class UsernameSherlockCrawler(BaseCrawler):
    """
    Wraps the Sherlock CLI to search 300+ sites for a given username.

    Sherlock manages its own HTTP requests, so Tor is not required.
    """

    platform = "username_sherlock"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.65
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.strip()

        if not await _check_sherlock_installed():
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="sherlock_not_installed",
                source_reliability=self.source_reliability,
            )

        try:
            found_on = await _run_sherlock(username)
        except TimeoutError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="sherlock_timeout",
                source_reliability=self.source_reliability,
            )
        except FileNotFoundError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="sherlock_not_installed",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=True,
            username=username,
            found_on=found_on,
            site_count=len(found_on),
        )
