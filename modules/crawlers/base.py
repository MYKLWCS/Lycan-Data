from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from modules.crawlers.core.models import CrawlerCategory, CrawlerHealth, RateLimit
from modules.crawlers.result import CrawlerResult
from shared.config import settings
from shared.tor import TorInstance, tor_manager

logger = logging.getLogger(__name__)

# Human-like delay range (seconds)
DELAY_MIN = 1.5
DELAY_MAX = 4.0

# Retry defaults
MAX_SCRAPER_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0

# Default rate limit for crawlers that don't override
_DEFAULT_RATE_LIMIT = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)


class BaseCrawler(ABC):
    """
    Abstract base for all scrapers.

    Implements the spec-09 interface (name, category, rate_limit,
    source_reliability, crawl, health_check, safe_crawl) while
    preserving the existing scrape()/run() contract.

    Subclass + register:
        @register("myplatform")
        class MyCrawler(BaseCrawler):
            platform = "myplatform"
            source_reliability = 0.6
            category = CrawlerCategory.SOCIAL_MEDIA
            requires_tor = True

            async def scrape(self, identifier: str) -> CrawlerResult:
                ...
    """

    platform: str = ""
    source_reliability: float = 0.5
    category: CrawlerCategory = CrawlerCategory.PEOPLE
    rate_limit: RateLimit = _DEFAULT_RATE_LIMIT
    requires_tor: bool = True
    tor_instance: TorInstance = TorInstance.TOR2
    proxy_tier: str = "tor"  # residential | datacenter | tor | direct -- override per crawler
    max_retries: int = MAX_SCRAPER_RETRIES

    @abstractmethod
    async def scrape(self, identifier: str) -> CrawlerResult:
        """
        Scrape a platform for the given identifier.
        identifier may be: username, phone, email, name -- depends on platform.
        Must always return a CrawlerResult, never raise.
        """

    async def run(self, identifier: str) -> CrawlerResult:
        """
        Public entry point. Wraps scrape() with:
        - Enabled check (kill switch)
        - Circuit breaker (skip if circuit open)
        - Retry with exponential backoff + jitter
        - Structured error logging
        - Human delay
        """
        # ── Kill switch ──────────────────────────────────────────────────────
        kill_switch = f"enable_{self.platform.replace('-', '_')}"
        if hasattr(settings, kill_switch) and not getattr(settings, kill_switch):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"{self.platform} disabled via kill switch",
            )

        # ── Circuit breaker ──────────────────────────────────────────────────
        from shared.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        if await cb.is_open(self.platform):
            logger.warning(
                "circuit_breaker_open | source=%s identifier=%s",
                self.platform,
                identifier,
            )
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"circuit_open: {self.platform} skipped (too many failures)",
            )

        # ── Retry loop with exponential backoff + jitter ─────────────────────
        last_error: str | None = None
        for attempt in range(self.max_retries):
            await self._human_delay()

            try:
                t0 = time.monotonic()
                result = await self.scrape(identifier)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                result.tor_used = self.requires_tor and settings.tor_enabled

                # Record success with circuit breaker
                await cb.record_success(self.platform)

                logger.info(
                    "scraper_success | source=%s identifier=%s "
                    "found=%s elapsed_ms=%d attempt=%d",
                    self.platform,
                    identifier,
                    result.found,
                    elapsed_ms,
                    attempt + 1,
                )
                return result

            except Exception as exc:
                last_error = str(exc)
                elapsed_ms = int((time.monotonic() - t0) * 1000)

                # ── Structured error log ─────────────────────────────────────
                logger.error(
                    "scraper_error | source=%s identifier=%s "
                    "error_type=%s error=%s elapsed_ms=%d "
                    "attempt=%d/%d timestamp=%s",
                    self.platform,
                    identifier,
                    type(exc).__name__,
                    last_error,
                    elapsed_ms,
                    attempt + 1,
                    self.max_retries,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )

                # Record failure with circuit breaker
                await cb.record_failure(self.platform)

                # Don't retry on the last attempt
                if attempt < self.max_retries - 1:
                    backoff = min(
                        BASE_BACKOFF_SECONDS * (2 ** attempt),
                        MAX_BACKOFF_SECONDS,
                    )
                    # Add jitter: +/- 30%
                    jitter = backoff * random.uniform(-0.3, 0.3)
                    wait = max(0.1, backoff + jitter)
                    logger.info(
                        "scraper_retry | source=%s identifier=%s "
                        "backoff=%.1fs attempt=%d/%d",
                        self.platform,
                        identifier,
                        wait,
                        attempt + 2,
                        self.max_retries,
                    )
                    await asyncio.sleep(wait)

        # All retries exhausted
        logger.error(
            "scraper_exhausted | source=%s identifier=%s "
            "error=%s retries=%d",
            self.platform,
            identifier,
            last_error,
            self.max_retries,
        )
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=False,
            error=last_error,
        )

    async def get_proxy_async(self) -> str | None:
        """
        Return the best available proxy for this crawler's tier preference.

        Falls back through the tier chain (residential -> datacenter -> tor -> direct)
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
        """Sync fallback -- returns Tor proxy or proxy_override."""
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

    # ── Spec-09 interface ────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Spec-09: crawler name (maps to platform)."""
        return self.platform

    async def crawl(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[CrawlerResult]:
        """
        Spec-09 crawl interface.  Delegates to scrape() and wraps the
        single result in a list for spec compliance.
        """
        result = await self.scrape(query)
        return [result]

    async def health_check(self) -> CrawlerHealth:
        """
        Spec-09: default health check — reports healthy unless the
        circuit breaker is open.
        """
        from shared.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        is_open = await cb.is_open(self.platform)
        return CrawlerHealth(
            healthy=not is_open,
            last_check=datetime.now(UTC),
            avg_latency_ms=0.0,
            success_rate=0.0 if is_open else 1.0,
            last_error="circuit_open" if is_open else None,
        )

    async def safe_crawl(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[CrawlerResult]:
        """
        Spec-09: crawl with circuit breaker, retry, and error handling.
        Delegates to the existing run() method which already has all of this.
        """
        result = await self.run(query)
        return [result]

    async def crawl_streaming(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[CrawlerResult, None]:
        """Spec-09: stream results one at a time."""
        results = await self.crawl(query, params)
        for r in results:
            yield r

    @staticmethod
    def hash_data(data: Dict[str, Any]) -> str:
        """SHA-256 hash of normalized data for dedup."""
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
