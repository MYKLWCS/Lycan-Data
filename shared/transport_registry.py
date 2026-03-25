"""
Per-domain transport preference registry backed by Dragonfly (Redis).

Tracks block counts per domain. After `threshold` blocks, auto-promotes the
domain to a faster-bypass transport tier. Falls back to in-memory dict if
Dragonfly is unavailable.

Transport tiers (in order of capability):
  httpx → curl (Chrome TLS) → flaresolverr (Cloudflare bypass)
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

_TIER_ORDER = ["httpx", "curl", "flaresolverr"]
_PREFIX = "transport:"
_BLOCK_PREFIX = "blocks:"


class TransportRegistry:
    def __init__(self, threshold: int = 3):
        self._threshold = threshold
        self._memory: dict[str, str] = {}
        self._blocks: dict[str, int] = defaultdict(int)
        self._redis = None

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url("redis://localhost:6379")
            await self._redis.ping()
        except Exception:
            self._redis = None
        return self._redis

    async def get_transport(self, domain: str) -> str:
        r = await self._get_redis()
        if r:
            try:
                val = await r.get(f"{_PREFIX}{domain}")
                return val.decode() if val else "httpx"
            except Exception:
                pass
        return self._memory.get(domain, "httpx")

    async def set_transport(self, domain: str, transport: str) -> None:
        r = await self._get_redis()
        if r:
            try:
                await r.set(f"{_PREFIX}{domain}", transport)
                return
            except Exception:
                pass
        self._memory[domain] = transport

    async def record_blocked(self, domain: str) -> None:
        r = await self._get_redis()
        count = 0
        if r:
            try:
                count = await r.incr(f"{_BLOCK_PREFIX}{domain}")
            except Exception:
                self._blocks[domain] += 1
                count = self._blocks[domain]
        else:
            self._blocks[domain] += 1
            count = self._blocks[domain]

        if count >= self._threshold:
            current = await self.get_transport(domain)
            idx = _TIER_ORDER.index(current) if current in _TIER_ORDER else 0
            if idx < len(_TIER_ORDER) - 1:
                new_transport = _TIER_ORDER[idx + 1]
                await self.set_transport(domain, new_transport)
                if r:
                    try:
                        await r.delete(f"{_BLOCK_PREFIX}{domain}")
                    except Exception:
                        pass
                self._blocks[domain] = 0
                logger.info(
                    "Domain %s promoted from %s to %s after %d blocks",
                    domain,
                    current,
                    new_transport,
                    count,
                )


transport_registry = TransportRegistry()
