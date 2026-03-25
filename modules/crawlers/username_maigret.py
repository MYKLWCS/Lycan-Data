"""
username_maigret.py — Maigret subprocess wrapper.

Searches 2000+ sites for a username using the maigret CLI tool.
Registered as "username_maigret".
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

MAIGRET_TIMEOUT = 300  # seconds — maigret checks 2000+ sites


def _run_maigret_sync(username: str, report_path: str) -> None:
    """Run maigret synchronously (called via asyncio.to_thread)."""
    subprocess.run(
        [
            "maigret",
            username,
            "--json",
            report_path,
            "--no-color",
            "--timeout",
            "10",
        ],
        capture_output=True,
        timeout=MAIGRET_TIMEOUT,
        check=False,
    )


@register("username_maigret")
class MaigretCrawler(BaseCrawler):
    """
    Wraps the Maigret CLI to search 2000+ sites for a given username.

    Maigret manages its own HTTP requests. Output is parsed from JSON.
    """

    platform = "username_maigret"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.65
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.strip()

        if not shutil.which("maigret"):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="maigret_not_installed",
                source_reliability=self.source_reliability,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = str(Path(tmpdir) / f"{username}.json")
            try:
                await asyncio.to_thread(_run_maigret_sync, username, report_path)
            except subprocess.TimeoutExpired:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="maigret_timeout",
                    source_reliability=self.source_reliability,
                )
            except FileNotFoundError:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="maigret_not_installed",
                    source_reliability=self.source_reliability,
                )

            path = Path(report_path)
            if not path.exists():
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="no_output",
                    source_reliability=self.source_reliability,
                )

            try:
                raw = json.loads(path.read_text())
            except Exception:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="invalid_json",
                    source_reliability=self.source_reliability,
                )

        # Maigret JSON: {site_name: {"status": {"status": "Claimed"}, "url": ...}}
        sites_found = []
        for site_name, info in raw.items():
            status_block = info.get("status", {})
            status = status_block.get("status", "")
            if status == "Claimed":
                sites_found.append(
                    {
                        "site": site_name,
                        "url": info.get("url", ""),
                        "status": status,
                    }
                )

        return self._result(
            identifier,
            found=True,
            username=username,
            sites_found=sites_found,
            site_count=len(sites_found),
        )
