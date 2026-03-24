"""
email_holehe.py — Holehe subprocess wrapper.

Checks if an email address is registered on 100+ services using the holehe CLI tool.
Registered as "email_holehe".
"""

from __future__ import annotations

import asyncio
import logging
import re

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

HOLEHE_TIMEOUT = 120  # seconds


async def _run_holehe(email: str) -> tuple[list[str], int]:
    """Run holehe subprocess, return (found_services, total_checked)."""
    proc = await asyncio.create_subprocess_exec(
        "holehe",
        email,
        "--only-used",
        "--no-color",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=HOLEHE_TIMEOUT)
    lines = stdout.decode(errors="replace").splitlines()
    found = [re.sub(r"\[.\]\s*", "", l).strip() for l in lines if l.startswith("[+]")]
    total = sum(1 for l in lines if l.startswith("[+]") or l.startswith("[-]"))
    return found, total


async def _check_holehe_installed() -> bool:
    """Return True if holehe is available on PATH."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "holehe",
            "--help",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return proc.returncode == 0
    except (TimeoutError, FileNotFoundError):
        return False


@register("email_holehe")
class EmailHoleheCrawler(BaseCrawler):
    """
    Wraps the Holehe CLI to check if an email is registered on 100+ services.

    Holehe manages its own HTTP requests, so Tor is not needed here.
    """

    platform = "email_holehe"
    source_reliability = 0.70
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        email = identifier.strip().lower()

        # Install check
        if not await _check_holehe_installed():
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="holehe_not_installed",
                source_reliability=self.source_reliability,
            )

        try:
            found_on, checked_count = await _run_holehe(email)
        except TimeoutError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="holehe_timeout",
                source_reliability=self.source_reliability,
            )
        except FileNotFoundError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="holehe_not_installed",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=True,
            email=email,
            found_on=found_on,
            checked_count=checked_count,
        )
