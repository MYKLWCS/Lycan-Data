"""
phone_phoneinfoga.py — PhoneInfoga CLI wrapper.

Runs OSINT on a phone number using the phoneinfoga Go binary.
Returns carrier, line type, country, and scan results.
Registered as "phone_phoneinfoga".
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

PHONEINFOGA_TIMEOUT = 120  # seconds


def _run_phoneinfoga_sync(number: str) -> bytes:
    """Run phoneinfoga synchronously (called via asyncio.to_thread)."""
    result = subprocess.run(
        [
            "phoneinfoga",
            "scan",
            "-n",
            number,
            "--output",
            "json",
        ],
        capture_output=True,
        timeout=PHONEINFOGA_TIMEOUT,
        check=False,
    )
    return result.stdout


@register("phone_phoneinfoga")
class PhoneInfogaCrawler(BaseCrawler):
    """
    Wraps the phoneinfoga Go binary to gather OSINT on phone numbers.

    Returns carrier info, line type, country, and scanner results.
    Requires phoneinfoga binary on PATH.
    """

    platform = "phone_phoneinfoga"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.60
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        number = identifier.strip()

        if not shutil.which("phoneinfoga"):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="phoneinfoga_not_installed",
                source_reliability=self.source_reliability,
            )

        try:
            stdout = await asyncio.to_thread(_run_phoneinfoga_sync, number)
        except subprocess.TimeoutExpired:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="phoneinfoga_timeout",
                source_reliability=self.source_reliability,
            )
        except FileNotFoundError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="phoneinfoga_not_installed",
                source_reliability=self.source_reliability,
            )

        if not stdout:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_output",
                source_reliability=self.source_reliability,
            )

        try:
            data = json.loads(stdout)
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        # phoneinfoga JSON output structure varies by version;
        # normalise the most common top-level fields
        result_data: dict = {}
        if isinstance(data, dict):
            result_data = data
        elif isinstance(data, list) and data:
            result_data = data[0]

        return self._result(
            identifier,
            found=True,
            phone=number,
            carrier=result_data.get("carrier", result_data.get("Carrier")),
            line_type=result_data.get("line_type", result_data.get("LineType")),
            country=result_data.get("country", result_data.get("Country")),
            local=result_data.get("local", result_data.get("Local")),
            international=result_data.get("international", result_data.get("International")),
            raw=result_data,
        )
