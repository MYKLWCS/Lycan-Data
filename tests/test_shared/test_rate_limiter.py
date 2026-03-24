"""
Tests for shared/rate_limiter.py

All tests use an in-memory fake Redis — no real infrastructure required.
The Lua evalsha path is mocked; unit tests exercise the Python-level logic.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from shared.rate_limiter import (
    RateLimiter,
    RateLimitSpec,
    _spec_for,
    get_rate_limiter,
    init_rate_limiter,
)

# ── Fake Redis ────────────────────────────────────────────────────────────────


class FakeRedis:
    """
    In-memory fake supporting HMGET/HMSET/EXPIRE/script_load/evalsha.

    evalsha runs the token-bucket logic locally so tests don't need
    a real Redis instance or Lua interpreter.
    """

    def __init__(self):
        self._store: dict[str, dict[str, str]] = {}
        self._sha_counter = 0

    async def script_load(self, script: str) -> str:
        self._sha_counter += 1
        return f"fake_sha_{self._sha_counter}"

    async def evalsha(self, sha, num_keys, key, rate, burst, now, requested, ttl):
        rate = float(rate)
        burst = float(burst)
        now = float(now)
        requested = float(requested)

        data = self._store.get(key, {})
        tokens = float(data.get("tokens", burst))
        last_refill = float(data.get("last_refill", now))

        elapsed = now - last_refill
        new_tokens = min(burst, tokens + elapsed * rate)

        if new_tokens >= requested:
            new_tokens -= requested
            self._store.setdefault(key, {})
            self._store[key]["tokens"] = f"{new_tokens:.4f}"
            self._store[key]["last_refill"] = f"{now:.6f}"
            return [1, f"{new_tokens:.4f}", 0]
        else:
            deficit = requested - new_tokens
            retry_ms = int((deficit / rate) * 1000) + 1
            self._store.setdefault(key, {})
            self._store[key]["tokens"] = f"{new_tokens:.4f}"
            self._store[key]["last_refill"] = f"{now:.6f}"
            return [0, f"{new_tokens:.4f}", retry_ms]

    async def hgetall(self, key: str) -> dict[bytes, bytes]:
        data = self._store.get(key, {})
        return {k.encode(): v.encode() for k, v in data.items()}

    async def delete(self, key: str):
        self._store.pop(key, None)

    async def expire(self, key: str, ttl: int):
        pass


def make_limiter() -> tuple[RateLimiter, FakeRedis]:
    redis = FakeRedis()
    limiter = RateLimiter(redis)
    return limiter, redis


# ── _spec_for ─────────────────────────────────────────────────────────────────


def test_spec_for_known_domain():
    spec = _spec_for("api.open.fec.gov")
    assert spec.rate == 2.0
    assert spec.burst == 10


def test_spec_for_partial_match():
    # "steamcommunity.com" appears in _DOMAIN_DEFAULTS; a sub-path should match
    spec = _spec_for("store.steamcommunity.com")
    assert spec.rate == 0.5


def test_spec_for_unknown_defaults():
    spec = _spec_for("totally-unknown-domain.xyz")
    assert spec.rate == 1.0
    assert spec.burst == 5


# ── RateLimitSpec factory methods ─────────────────────────────────────────────


def test_spec_conservative():
    s = RateLimitSpec.conservative()
    assert s.rate == 1.0
    assert s.burst == 3


def test_spec_moderate():
    s = RateLimitSpec.moderate()
    assert s.rate == 2.0
    assert s.burst == 10


def test_spec_aggressive():
    s = RateLimitSpec.aggressive()
    assert s.rate == 5.0
    assert s.burst == 20


# ── Requests within burst limit are allowed immediately ───────────────────────


@pytest.mark.asyncio
async def test_acquire_within_burst_succeeds():
    limiter, _ = make_limiter()
    # burst=5 → first 5 calls should complete without sleeping
    for _ in range(5):
        await limiter.acquire("test.domain", rate=10.0, burst=5)


@pytest.mark.asyncio
async def test_acquire_no_redis_always_passes():
    limiter = RateLimiter(redis_client=None)
    # Should return immediately without error
    await limiter.acquire("any.domain", rate=1.0, burst=1)


# ── Requests exceeding limit are rejected / sleep ────────────────────────────


@pytest.mark.asyncio
async def test_acquire_over_limit_sleeps():
    """After burst is exhausted, acquire should sleep before succeeding."""
    limiter, redis = make_limiter()
    key = "throttled.domain"

    # Exhaust the burst of 2
    await limiter.acquire(key, rate=1.0, burst=2)
    await limiter.acquire(key, rate=1.0, burst=2)

    # Third call needs a token — should sleep (mock asyncio.sleep to intercept)
    sleep_calls = []

    async def fake_sleep(s):
        sleep_calls.append(s)
        # Advance time by injecting tokens directly so the retry succeeds
        rk = f"lycan:rl:{key}"
        redis._store.setdefault(rk, {})
        redis._store[rk]["tokens"] = "2.0000"
        redis._store[rk]["last_refill"] = f"{time.time():.6f}"

    with patch("shared.rate_limiter.asyncio.sleep", side_effect=fake_sleep):
        await limiter.acquire(key, rate=1.0, burst=2)

    assert len(sleep_calls) >= 1


@pytest.mark.asyncio
async def test_acquire_raises_on_max_wait_exceeded():
    """If retry_after keeps exceeding max_wait_seconds, TimeoutError is raised."""
    limiter, _ = make_limiter()
    key = "very.slow.domain"

    # Pre-fill with 0 tokens so every call returns a long retry
    rk = f"lycan:rl:{key}"
    limiter._redis._store[rk] = {"tokens": "0.0000", "last_refill": f"{time.time():.6f}"}

    with pytest.raises(TimeoutError):
        # max_wait_seconds=0 ensures the very first non-zero retry blows up
        await limiter.acquire(key, rate=0.001, burst=1, max_wait_seconds=0.0)


# ── Window resets correctly ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tokens_refill_over_time():
    """
    Simulate elapsed time by backdating last_refill so the token bucket
    refills and a new acquire succeeds without sleeping.
    """
    limiter, redis = make_limiter()
    key = "refill.test"
    rk = f"lycan:rl:{key}"

    # Exhaust burst of 1
    await limiter.acquire(key, rate=1.0, burst=1)
    assert float(redis._store[rk]["tokens"]) < 1.0

    # Wind back last_refill by 2 seconds — should add 2 tokens (capped at burst=1)
    redis._store[rk]["last_refill"] = str(time.time() - 2.0)

    # Should now acquire without sleeping
    await limiter.acquire(key, rate=1.0, burst=1)


# ── Key isolation ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_keys_are_isolated():
    """
    Exhausting the token bucket for key A must not affect key B.
    """
    limiter, redis = make_limiter()

    # Exhaust key A (burst=1)
    await limiter.acquire("key_a", rate=1.0, burst=1)
    rk_a = "lycan:rl:key_a"
    assert float(redis._store[rk_a]["tokens"]) < 1.0

    # key B should still have a full bucket
    rk_b = "lycan:rl:key_b"
    assert rk_b not in redis._store  # untouched

    await limiter.acquire("key_b", rate=1.0, burst=1)
    # key B acquired successfully — its own bucket was used
    assert rk_b in redis._store


# ── peek ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_peek_returns_burst_when_no_data():
    limiter, _ = make_limiter()
    tokens = await limiter.peek("unknown.key")
    # _spec_for("unknown.key") → __default__ burst=5
    assert tokens == 5.0


@pytest.mark.asyncio
async def test_peek_returns_current_tokens():
    limiter, redis = make_limiter()
    key = "peek.test"
    rk = f"lycan:rl:{key}"
    redis._store[rk] = {"tokens": "3.1400", "last_refill": str(time.time())}
    tokens = await limiter.peek(key)
    assert abs(tokens - 3.14) < 0.01


@pytest.mark.asyncio
async def test_peek_no_redis_returns_burst():
    limiter = RateLimiter(redis_client=None)
    tokens = await limiter.peek("any.domain")
    assert tokens == float(_spec_for("any.domain").burst)


# ── reset ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_clears_bucket():
    limiter, redis = make_limiter()
    key = "reset.test"
    rk = f"lycan:rl:{key}"
    redis._store[rk] = {"tokens": "0.0000", "last_refill": str(time.time())}

    await limiter.reset(key)
    assert rk not in redis._store


@pytest.mark.asyncio
async def test_reset_no_redis_is_noop():
    limiter = RateLimiter(redis_client=None)
    # Should not raise
    await limiter.reset("any.domain")


# ── Module-level singleton ────────────────────────────────────────────────────


def test_get_rate_limiter_returns_instance():
    rl = get_rate_limiter()
    assert isinstance(rl, RateLimiter)


def test_init_rate_limiter_replaces_global():
    redis = FakeRedis()
    rl = init_rate_limiter(redis)
    assert isinstance(rl, RateLimiter)
    assert rl._redis is redis
    assert get_rate_limiter() is rl
