from __future__ import annotations
import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any

import httpx

from shared.config import settings
from shared.constants import SOURCE_RELIABILITY
from shared.tor import tor_manager, TorInstance
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# Human-like delay range (seconds)
DELAY_MIN = 1.5
DELAY_MAX = 4.0


class BaseCrawler(ABC):
    """
    Abstract base for all scrapers.

    Subclass + register:
        @register("myplatform")
        class MyCrawler(BaseCrawler):
            platform = "myplatform"
            source_reliability = 0.6
            requires_tor = True

            async def scrape(self, identifier: str) -> CrawlerResult:
                ...
    """

    platform: str = ""
    source_reliability: float = 0.5
    requires_tor: bool = True
    tor_instance: TorInstance = TorInstance.TOR2

    @abstractmethod
    async def scrape(self, identifier: str) -> CrawlerResult:
        """
        Scrape a platform for the given identifier.
        identifier may be: username, phone, email, name — depends on platform.
        Must always return a CrawlerResult, never raise.
        """

    async def run(self, identifier: str) -> CrawlerResult:
        """
        Public entry point. Wraps scrape() with:
        - Enabled check (kill switch)
        - Delay
        - Error catching
        """
        kill_switch = f"enable_{self.platform.replace('-', '_')}"
        if hasattr(settings, kill_switch) and not getattr(settings, kill_switch):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"{self.platform} disabled via kill switch",
            )

        await self._human_delay()

        try:
            result = await self.scrape(identifier)
            result.tor_used = self.requires_tor and settings.tor_enabled
            return result
        except Exception as exc:
            logger.exception("Crawler %s failed for %s", self.platform, identifier)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
            )

    def get_proxy(self) -> str | None:
        """Return proxy URL for this crawler's Tor instance."""
        if not self.requires_tor:
            return None
        proxy = tor_manager.get_proxy(self.tor_instance)
        return proxy or None

    async def rotate_circuit(self) -> None:
        """Request new Tor circuit on block/ban detection."""
        await tor_manager.new_circuit(self.tor_instance)
        logger.info("Rotated Tor circuit for %s", self.platform)

    @staticmethod
    async def _human_delay() -> None:
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        await asyncio.sleep(delay)

    def _result(self, identifier: str, found: bool, **data: Any) -> CrawlerResult:
        """Shorthand to build a CrawlerResult."""
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=found,
            data=data,
            source_reliability=self.source_reliability,
        )
