from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any

from modules.crawlers.result import CrawlerResult
from shared.config import settings
from shared.tor import TorInstance, tor_manager

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
    proxy_tier: str = "tor"  # residential | datacenter | tor | direct — override per crawler

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

    async def get_proxy_async(self) -> str | None:
        """
        Return the best available proxy for this crawler's tier preference.

        Falls back through the tier chain (residential → datacenter → tor → direct)
        when the preferred tier has no healthy proxies available.
        """
        from shared.proxy_pool import proxy_pool

        # Crawler explicitly opts out of all proxying
        if not self.requires_tor and self.proxy_tier == "tor":
            return None

        # Resolve effective tier: honour proxy_tier unless it's "tor" and Tor is disabled
        tier = self.proxy_tier
        if tier == "tor" and not settings.tor_enabled:
            tier = "datacenter"

        proxy, _tier_used = await proxy_pool.next_with_fallback(tier)
        return proxy

    def get_proxy(self) -> str | None:
        """Sync fallback — returns Tor proxy or proxy_override."""
        if not self.requires_tor:
            return None
        if settings.proxy_override:
            return settings.proxy_override
        return tor_manager.get_proxy(self.tor_instance) or None

    async def rotate_circuit(self) -> None:
        """Request new Tor circuit on block/ban detection."""
        await tor_manager.new_circuit(self.tor_instance)
        logger.info("Rotated Tor circuit for %s", self.platform)

    @staticmethod
    async def _human_delay() -> None:
        base = random.uniform(settings.human_delay_min, settings.human_delay_max)
        if settings.jitter_enabled:
            base *= random.uniform(0.8, 1.2)
        await asyncio.sleep(base)

    async def _handle_ban_response(self, proxy: str | None, status_code: int) -> None:
        """
        Call this when a ban signal is detected (403, 429, 503 with captcha).

        Marks the proxy as banned in the pool and requests a fresh Tor circuit
        so the next request gets a new exit IP.
        """
        if proxy and status_code in (403, 429, 503):
            from shared.proxy_pool import proxy_pool

            await proxy_pool.mark_banned(proxy, duration_minutes=20)
            await self.rotate_circuit()

    def _result(self, identifier: str, found: bool, **data: Any) -> CrawlerResult:
        """Shorthand to build a CrawlerResult."""
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=found,
            data=data,
            source_reliability=self.source_reliability,
        )
