"""
Multi-layer proxy pool for Lycan-Data crawlers.

Tier priority (highest anonymity first):
  1. residential  — ISP-assigned IPs, lowest detection rate
  2. datacenter   — Fast, cheap, higher ban risk
  3. tor          — Delegates to TorManager
  4. direct       — No proxy (fallback only)

Usage:
    proxy = await proxy_pool.next(tier="residential")
    # returns "http://user:pass@host:port" or None

    await proxy_pool.mark_banned(proxy, duration_minutes=30)
    await proxy_pool.mark_slow(proxy)
"""

import asyncio
import logging
import time

from shared.config import settings
from shared.tor import TorInstance, tor_manager

logger = logging.getLogger(__name__)


class ProxyPool:
    """
    Manages a tiered pool of outbound proxies with health tracking and
    round-robin selection. Thread-safe via asyncio.Lock.

    Tier chain (highest anonymity → lowest):
        residential → datacenter → tor → direct

    Proxies are loaded from settings at instantiation and can be added
    at runtime via add_proxy(). Banned proxies are automatically unbanned
    after their cooldown period expires; slow proxies are deprioritised
    but not excluded unless healthier alternatives exist.
    """

    def __init__(self) -> None:
        self._residential: list[str] = []
        self._datacenter: list[str] = []
        self._banned: dict[str, float] = {}   # proxy_url → unban_timestamp
        self._slow: set[str] = set()
        self._lock = asyncio.Lock()
        self._rr_indices: dict[str, int] = {"residential": 0, "datacenter": 0}
        self._tor_manager = tor_manager  # capture at construction time
        self._load_from_settings()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _load_from_settings(self) -> None:
        """Parse comma-separated proxy lists from settings."""
        if settings.residential_proxies:
            self._residential = [
                p.strip()
                for p in settings.residential_proxies.split(",")
                if p.strip()
            ]
        if settings.datacenter_proxies:
            self._datacenter = [
                p.strip()
                for p in settings.datacenter_proxies.split(",")
                if p.strip()
            ]
        logger.debug(
            "ProxyPool loaded — residential: %d, datacenter: %d",
            len(self._residential),
            len(self._datacenter),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def next(self, tier: str = "residential") -> str | None:
        """
        Return the next available proxy for the requested tier.

        Returns None when:
        - tier == "direct" (no proxy)
        - tier == "tor" and Tor is disabled/unreachable
        - the pool for the tier is empty or all proxies are banned
        """
        async with self._lock:
            self._unban_expired()
            if tier == "residential":
                return self._next_from(self._residential, "residential")
            if tier == "datacenter":
                return self._next_from(self._datacenter, "datacenter")
            if tier == "tor":
                proxy = self._tor_manager.get_proxy(TorInstance.TOR2)
                return proxy or None
            # tier == "direct"
            return None

    async def next_with_fallback(
        self, preferred_tier: str = "residential"
    ) -> tuple[str | None, str]:
        """
        Try the preferred tier, then fall back through the chain until a
        proxy is found or we reach "direct".

        Returns:
            (proxy_url, tier_used)
            proxy_url is None when tier_used == "direct".
        """
        tier_chain = ["residential", "datacenter", "tor", "direct"]
        start = tier_chain.index(preferred_tier) if preferred_tier in tier_chain else 0
        for tier in tier_chain[start:]:
            proxy = await self.next(tier)
            if proxy is not None or tier == "direct":
                if tier != preferred_tier:
                    logger.info(
                        "ProxyPool: fell back from '%s' → '%s'", preferred_tier, tier
                    )
                return proxy, tier
        return None, "direct"  # pragma: no cover

    async def mark_banned(self, proxy: str, duration_minutes: int = 30) -> None:
        """Mark a proxy as banned for duration_minutes. It will auto-recover."""
        async with self._lock:
            self._banned[proxy] = time.time() + duration_minutes * 60
            logger.warning(
                "Proxy banned for %dm: %s…", duration_minutes, proxy[:40]
            )

    async def mark_slow(self, proxy: str) -> None:
        """Deprioritise a proxy — it will only be used when no healthy proxy exists."""
        async with self._lock:
            self._slow.add(proxy)
            logger.debug("Proxy marked slow: %s…", proxy[:40])

    async def mark_healthy(self, proxy: str) -> None:
        """Clear slow/banned flags for a proxy."""
        async with self._lock:
            self._slow.discard(proxy)
            self._banned.pop(proxy, None)
            logger.debug("Proxy marked healthy: %s…", proxy[:40])

    def add_proxy(self, proxy_url: str, tier: str = "residential") -> None:
        """Dynamically add a proxy at runtime (no lock needed — list append is GIL-safe)."""
        if tier == "residential":
            if proxy_url not in self._residential:
                self._residential.append(proxy_url)
                logger.info("Added residential proxy: %s…", proxy_url[:40])
        elif tier == "datacenter":
            if proxy_url not in self._datacenter:
                self._datacenter.append(proxy_url)
                logger.info("Added datacenter proxy: %s…", proxy_url[:40])

    def status(self) -> dict:
        """Return a health snapshot of the pool (does not require the lock)."""
        self._unban_expired()
        res_available = [
            p for p in self._residential if p not in self._banned and p not in self._slow
        ]
        dc_available = [
            p for p in self._datacenter if p not in self._banned and p not in self._slow
        ]
        return {
            "residential_total": len(self._residential),
            "residential_available": len(res_available),
            "residential_slow": len(
                [p for p in self._residential if p in self._slow]
            ),
            "datacenter_total": len(self._datacenter),
            "datacenter_available": len(dc_available),
            "datacenter_slow": len(
                [p for p in self._datacenter if p in self._slow]
            ),
            "banned_count": len(self._banned),
            "slow_count": len(self._slow),
            "tor_available": self._tor_manager.any_available(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_from(self, pool: list[str], key: str) -> str | None:
        """
        Round-robin selection from pool, skipping banned proxies.
        Slow proxies are used only when no healthy proxy is available.
        """
        if not pool:
            return None

        healthy = [p for p in pool if p not in self._banned and p not in self._slow]
        if healthy:
            candidates = healthy
        else:
            # Fall back to slow-but-not-banned proxies
            candidates = [p for p in pool if p not in self._banned]

        if not candidates:
            return None

        idx = self._rr_indices.get(key, 0) % len(candidates)
        self._rr_indices[key] = idx + 1
        return candidates[idx]

    def _unban_expired(self) -> None:
        """Remove entries whose ban period has elapsed. Must be called under the lock."""
        now = time.time()
        expired = [k for k, v in self._banned.items() if v <= now]
        for proxy in expired:
            del self._banned[proxy]
            logger.info("Proxy auto-unbanned: %s…", proxy[:40])


# Module-level singleton — import and use directly
proxy_pool = ProxyPool()
