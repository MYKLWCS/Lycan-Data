"""
Rate Limiter — Redis/Dragonfly-backed token bucket per domain/key.

Provides adaptive per-domain rate limiting for the crawler pipeline.
The token bucket state is stored in Dragonfly so all workers share the
same rate window (prevents process-level over-rate).

Usage:
    limiter = RateLimiter(redis_client)
    await limiter.acquire("twitter.com", rate=1.0, burst=5)
    # blocks until a token is available, then returns
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Key schema: lycan:rl:{key}  →  Hash {tokens, last_refill}
_KEY_PREFIX = "lycan:rl:"
_KEY_TTL = 3600  # 1 hour — keys auto-expire when idle


@dataclass
class RateLimitSpec:
    """Rate limit specification for a domain/key."""

    rate: float   # tokens per second (e.g. 1.0 = 1 req/s)
    burst: int    # maximum burst size (max simultaneous tokens)

    @classmethod
    def conservative(cls) -> "RateLimitSpec":
        """1 request per second, burst 3."""
        return cls(rate=1.0, burst=3)

    @classmethod
    def moderate(cls) -> "RateLimitSpec":
        """2 requests per second, burst 10."""
        return cls(rate=2.0, burst=10)

    @classmethod
    def aggressive(cls) -> "RateLimitSpec":
        """5 requests per second, burst 20."""
        return cls(rate=5.0, burst=20)


# Default per-domain rate limits — keyed by partial domain match.
# Exact key match tried first; then first matching prefix.
_DOMAIN_DEFAULTS: dict[str, RateLimitSpec] = {
    # Public government APIs — can handle higher throughput
    "api.open.fec.gov":          RateLimitSpec(rate=2.0, burst=10),
    "api.opensanctions.org":     RateLimitSpec(rate=1.0, burst=5),
    "namus.gov":                 RateLimitSpec(rate=0.5, burst=2),
    # Social platforms — conservative to avoid bans
    "mastodon.social":           RateLimitSpec(rate=1.0, burst=5),
    "steamcommunity.com":        RateLimitSpec(rate=0.5, burst=3),
    "api.twitch.tv":             RateLimitSpec(rate=5.0, burst=20),
    "api.spotify.com":           RateLimitSpec(rate=2.0, burst=10),
    # Sanctions/bulk data — cached, minimal rate needed
    "ofsistorage.blob.core.windows.net": RateLimitSpec(rate=0.1, burst=1),
    "webgate.ec.europa.eu":      RateLimitSpec(rate=0.1, burst=1),
    "www.treasury.gov":          RateLimitSpec(rate=0.2, burst=2),
    # Default for unknown domains
    "__default__":               RateLimitSpec(rate=1.0, burst=5),
}


def _spec_for(domain: str) -> RateLimitSpec:
    """Look up RateLimitSpec for a domain. Falls back to __default__."""
    if domain in _DOMAIN_DEFAULTS:
        return _DOMAIN_DEFAULTS[domain]
    # Try partial match (e.g. "api.twitter.com" matches "twitter.com")
    for key, spec in _DOMAIN_DEFAULTS.items():
        if key != "__default__" and key in domain:
            return spec
    return _DOMAIN_DEFAULTS["__default__"]


class RateLimiter:
    """
    Redis/Dragonfly-backed token bucket rate limiter.

    One token bucket per key (typically: domain or crawler platform name).
    Uses a Lua-based atomic refill+consume to prevent race conditions.

    Falls back to in-process asyncio.sleep if Redis is unavailable.
    """

    # Lua script: atomic token bucket refill and consume
    # Returns [acquired: 0|1, tokens_remaining: float, retry_after_ms: int]
    _LUA_ACQUIRE = """
local key        = KEYS[1]
local rate       = tonumber(ARGV[1])   -- tokens per second
local burst      = tonumber(ARGV[2])   -- max tokens (bucket capacity)
local now        = tonumber(ARGV[3])   -- current unix time (float seconds)
local requested  = tonumber(ARGV[4])   -- tokens requested (typically 1)
local ttl        = tonumber(ARGV[5])   -- key TTL in seconds

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens      = tonumber(data[1]) or burst
local last_refill = tonumber(data[2]) or now

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
local new_tokens = math.min(burst, tokens + elapsed * rate)

if new_tokens >= requested then
    -- Consume token
    new_tokens = new_tokens - requested
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, ttl)
    local retry_ms = 0
    return {1, string.format('%.4f', new_tokens), retry_ms}
else
    -- Not enough tokens — compute wait time
    local deficit = requested - new_tokens
    local retry_ms = math.ceil((deficit / rate) * 1000)
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, ttl)
    return {0, string.format('%.4f', new_tokens), retry_ms}
end
"""

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._script_sha: str | None = None

    async def acquire(
        self,
        key: str,
        *,
        rate: float | None = None,
        burst: int | None = None,
        max_wait_seconds: float = 30.0,
    ) -> None:
        """
        Acquire one token for `key`. Blocks until a token is available.

        If `rate`/`burst` are None, uses the domain-specific defaults from
        _DOMAIN_DEFAULTS (or __default__ if no match).

        Raises asyncio.TimeoutError if max_wait_seconds is exceeded.
        """
        spec = _spec_for(key)
        effective_rate = rate if rate is not None else spec.rate
        effective_burst = burst if burst is not None else spec.burst

        waited = 0.0
        while True:
            retry_after_ms = await self._try_acquire(
                key, effective_rate, effective_burst
            )
            if retry_after_ms == 0:
                return  # token acquired

            wait_s = retry_after_ms / 1000.0
            if waited + wait_s > max_wait_seconds:
                raise asyncio.TimeoutError(
                    f"Rate limit wait exceeded {max_wait_seconds}s for key={key!r}"
                )

            logger.debug(
                "Rate limiter: key=%r sleeping %.2fs (rate=%.1f burst=%d)",
                key, wait_s, effective_rate, effective_burst,
            )
            await asyncio.sleep(wait_s)
            waited += wait_s

    async def _try_acquire(self, key: str, rate: float, burst: int) -> int:
        """
        Attempt to acquire one token. Returns retry_after_ms (0 if acquired).
        Falls back to 0 (no limit) if Redis is unavailable.
        """
        if self._redis is None:
            return 0

        redis_key = f"{_KEY_PREFIX}{key}"
        now = time.time()

        try:
            # Load script on first use
            if self._script_sha is None:
                self._script_sha = await self._redis.script_load(self._LUA_ACQUIRE)

            result = await self._redis.evalsha(
                self._script_sha,
                1,
                redis_key,
                str(rate),
                str(burst),
                f"{now:.6f}",
                "1",  # tokens requested
                str(_KEY_TTL),
            )

            acquired = int(result[0])
            retry_ms = int(result[2])
            return 0 if acquired else max(retry_ms, 10)

        except Exception as exc:
            logger.debug("RateLimiter Redis error for key=%r: %s", key, exc)
            return 0  # fail open — don't block on Redis outage

    async def peek(self, key: str) -> float:
        """Return current token count for a key (non-consuming). Returns burst if no data."""
        if self._redis is None:
            spec = _spec_for(key)
            return float(spec.burst)
        redis_key = f"{_KEY_PREFIX}{key}"
        try:
            data = await self._redis.hgetall(redis_key)
            if not data:
                return float(_spec_for(key).burst)
            tokens = data.get(b"tokens", data.get("tokens", b"0"))
            return float(tokens)
        except Exception:
            return float(_spec_for(key).burst)

    async def reset(self, key: str) -> None:
        """Reset (delete) the token bucket for a key."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"{_KEY_PREFIX}{key}")
        except Exception as exc:
            logger.debug("RateLimiter reset error for key=%r: %s", key, exc)


# Module-level singleton — initialized lazily in get_rate_limiter()
_global_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Return the global rate limiter. Call init_rate_limiter() first."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter


def init_rate_limiter(redis_client) -> RateLimiter:
    """Initialize (or re-initialize) the global rate limiter with a Redis client."""
    global _global_limiter
    _global_limiter = RateLimiter(redis_client)
    return _global_limiter
