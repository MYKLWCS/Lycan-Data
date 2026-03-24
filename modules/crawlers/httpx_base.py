from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from modules.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


def _domain_from_url(url: str) -> str:
    """Extract the hostname from a URL for rate-limiter/circuit-breaker keying."""
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


class HttpxCrawler(BaseCrawler):
    """
    Lightweight httpx-based scraper for APIs and simple pages.
    No browser — fast, low resource.

    Integrates with:
    - RateLimiter (shared/rate_limiter.py): token bucket per domain
    - CircuitBreaker (shared/circuit_breaker.py): per-domain failure tracking
    Both degrade gracefully when Redis is unavailable.
    """

    def _client(self, **kwargs: Any) -> httpx.AsyncClient:
        """Build AsyncClient with optional SOCKS5 proxy (httpx 0.28+ compatible)."""
        proxy = self.get_proxy()
        transport = None
        if proxy:
            try:
                transport = httpx.AsyncHTTPTransport(proxy=proxy)
            except Exception:
                pass  # proxy unavailable — run direct
        return httpx.AsyncClient(
            transport=transport,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LycanBot/1.0)"},
            **kwargs,
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """
        GET with rate limiting, circuit breaker, Tor proxy, and timeout.
        Returns None on error. Never raises.
        """
        domain = _domain_from_url(url)

        # Circuit breaker check — block if domain is in OPEN state
        from shared.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        if await cb.is_open(domain):
            logger.warning("httpx GET blocked by circuit breaker: %s", domain)
            return None

        # Rate limiter — wait for token before sending
        from shared.rate_limiter import get_rate_limiter

        try:
            await get_rate_limiter().acquire(domain)
        except Exception as exc:
            logger.debug("Rate limiter acquire failed for %s: %s", domain, exc)

        try:
            async with self._client() as client:
                response = await client.get(url, **kwargs)
            await cb.record_success(domain)
            return response
        except Exception as exc:
            logger.warning("httpx GET failed for %s: %s", url, exc)
            await cb.record_failure(domain)
            return None

    async def post(self, url: str, **kwargs: Any) -> httpx.Response | None:
        """
        POST with rate limiting, circuit breaker, Tor proxy, and timeout.
        Returns None on error. Never raises.
        """
        domain = _domain_from_url(url)

        from shared.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        if await cb.is_open(domain):
            logger.warning("httpx POST blocked by circuit breaker: %s", domain)
            return None

        from shared.rate_limiter import get_rate_limiter

        try:
            await get_rate_limiter().acquire(domain)
        except Exception as exc:
            logger.debug("Rate limiter acquire failed for %s: %s", domain, exc)

        try:
            async with self._client() as client:
                response = await client.post(url, **kwargs)
            await cb.record_success(domain)
            return response
        except Exception as exc:
            logger.warning("httpx POST failed for %s: %s", url, exc)
            await cb.record_failure(domain)
            return None
