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
from typing import Any

from modules.crawlers.core.models import CrawlerCategory, CrawlerHealth, RateLimit
from modules.crawlers.core.result import CrawlerResult
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
                    "scraper_success | source=%s identifier=%s found=%s elapsed_ms=%d attempt=%d",
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
                        BASE_BACKOFF_SECONDS * (2**attempt),
                        MAX_BACKOFF_SECONDS,
                    )
                    # Add jitter: +/- 30%
                    jitter = backoff * random.uniform(-0.3, 0.3)
                    wait = max(0.1, backoff + jitter)
                    logger.info(
                        "scraper_retry | source=%s identifier=%s backoff=%.1fs attempt=%d/%d",
                        self.platform,
                        identifier,
                        wait,
                        attempt + 2,
                        self.max_retries,
                    )
                    await asyncio.sleep(wait)

        # All retries exhausted
        logger.error(
            "scraper_exhausted | source=%s identifier=%s error=%s retries=%d",
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

        if settings.proxy_override:
            return settings.proxy_override

        preferred_tier = self._preferred_proxy_tier()
        if preferred_tier is None:
            return None

        # Resolve effective tier: honour proxy_tier unless it's "tor" and Tor is disabled
        tier = preferred_tier
        if tier == "tor" and not settings.tor_enabled:
            tier = "datacenter"

        proxy, _tier_used = await proxy_pool.next_with_fallback(tier)
        return proxy

    def get_proxy(self) -> str | None:
        """Return the best available proxy for the crawler's preferred tier."""
        if settings.proxy_override:
            return settings.proxy_override

        preferred_tier = self._preferred_proxy_tier()
        if preferred_tier is None:
            return None

        for tier in self._tier_chain(preferred_tier):
            proxy = self._proxy_for_tier(tier)
            if proxy is not None or tier == "direct":
                return proxy

        return None

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

    async def crawl(self, query: str, params: dict[str, Any] | None = None) -> list[CrawlerResult]:
        """
        Spec-09 crawl interface.  Delegates to scrape() and wraps the
        single result in a list for spec compliance.
        """
        result = await self.scrape(self._merge_query_and_params(query, params))
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
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[CrawlerResult]:
        """
        Spec-09: crawl with circuit breaker, retry, and error handling.
        Delegates to the existing run() method which already has all of this.
        """
        result = await self.run(query)
        return [result]

    async def crawl_streaming(
        self, query: str, params: dict[str, Any] | None = None
    ) -> AsyncGenerator[CrawlerResult, None]:
        """Spec-09: stream results one at a time."""
        results = await self.crawl(query, params)
        for r in results:
            yield r

    @staticmethod
    def hash_data(data: dict[str, Any]) -> str:
        """SHA-256 hash of normalized data for dedup."""
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _preferred_proxy_tier(self) -> str | None:
        """
        Resolve the crawler's preferred proxy tier.

        If a crawler explicitly sets proxy_tier, honour it. Otherwise, only
        default to Tor when the crawler explicitly requires Tor.
        """
        explicit_tier = None
        if "proxy_tier" in self.__dict__:
            explicit_tier = self.__dict__["proxy_tier"]
        elif "proxy_tier" in self.__class__.__dict__:
            explicit_tier = self.__class__.__dict__["proxy_tier"]

        if explicit_tier is not None:
            return None if explicit_tier == "direct" else explicit_tier
        if self.requires_tor:
            return "tor"
        return None

    @staticmethod
    def _tier_chain(preferred_tier: str) -> list[str]:
        tiers = ["residential", "datacenter", "tor", "direct"]
        if preferred_tier not in tiers:
            return ["direct"]
        start = tiers.index(preferred_tier)
        return tiers[start:]

    def _proxy_for_tier(self, tier: str) -> str | None:
        if tier == "residential" and settings.residential_proxies:
            proxies = [p.strip() for p in settings.residential_proxies.split(",") if p.strip()]
            if proxies:
                return random.choice(proxies)

        if tier == "datacenter" and settings.datacenter_proxies:
            proxies = [p.strip() for p in settings.datacenter_proxies.split(",") if p.strip()]
            if proxies:
                return random.choice(proxies)

        if tier == "tor" and settings.tor_enabled:
            return tor_manager.get_proxy(self.tor_instance) or None

        return None

    @staticmethod
    def _merge_query_and_params(query: str, params: dict[str, Any] | None = None) -> str:
        """
        Build a single identifier string for legacy scrape(query: str) crawlers.

        The builder pipeline routes structured params into crawl(query, params),
        but most crawlers still accept one string. Preserve the high-signal
        fields instead of dropping them.
        """
        if not params:
            return query

        query = (query or "").strip()
        explicit_name = str(params.get("name") or "").strip()
        name = explicit_name or query
        location = str(params.get("location") or "").strip()
        if not location:
            city = str(params.get("city") or "").strip()
            state = str(params.get("state") or params.get("state_code") or "").strip()
            zip_code = str(params.get("zip") or params.get("postal_code") or "").strip()
            if city and state:
                location = f"{city},{state}"
            elif city:
                location = city
            elif state:
                location = state
            elif zip_code:
                location = zip_code
        if name and location and name != location:
            return f"{name}|{location}"
        if location:
            return location
        if explicit_name:
            return explicit_name

        for key in (
            "email",
            "phone",
            "username",
            "company_name",
            "company",
            "domain",
            "query",
            "state",
            "location",
        ):
            value = params.get(key)
            if value:
                return str(value).strip()

        return query
