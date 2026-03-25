"""
test_transport_registry_wave5.py — Coverage gap tests for shared/transport_registry.py.

Targets:
  - Lines 83-84: await r.delete(...) inside the try block of record_blocked().
    This branch executes when: Redis is available, count >= threshold, current
    transport is not the last tier (promotion is possible), and r.delete succeeds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.transport_registry import TransportRegistry, _TIER_ORDER


# ---------------------------------------------------------------------------
# Fake Redis with controllable delete
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self):
        self._store: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self.delete = AsyncMock()

    async def ping(self):
        return True

    async def get(self, key: str):
        val = self._store.get(key)
        return val.encode() if val else None

    async def set(self, key: str, value: str):
        self._store[key] = value

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]


# ---------------------------------------------------------------------------
# Line 83: r.delete() called when promotion fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_blocked_calls_redis_delete_on_promotion():
    """
    Lines 83-84: When Redis is available and count reaches threshold,
    TransportRegistry promotes the domain and calls r.delete() to clear
    the block counter.
    """
    registry = TransportRegistry(threshold=3)
    fake_r = FakeRedis()
    registry._redis = fake_r

    domain = "example.com"

    # Pre-set count so that the next incr hits exactly the threshold
    fake_r._counts[f"blocks:{domain}"] = 2  # next incr → 3 == threshold

    await registry.record_blocked(domain)

    # delete should have been called on the block counter key
    fake_r.delete.assert_awaited_once_with(f"blocks:{domain}")


@pytest.mark.asyncio
async def test_record_blocked_promotes_transport_tier():
    """
    Verify that the domain is promoted from httpx → curl when threshold is reached.
    This exercises the same branch path that contains lines 83-84.
    """
    registry = TransportRegistry(threshold=2)
    fake_r = FakeRedis()
    registry._redis = fake_r

    domain = "promoted.com"

    # First incr → 1 (below threshold, no promotion)
    await registry.record_blocked(domain)
    assert fake_r.delete.await_count == 0

    # Second incr → 2 (== threshold, triggers promotion + delete)
    await registry.record_blocked(domain)
    assert fake_r.delete.await_count == 1
    fake_r.delete.assert_awaited_with(f"blocks:{domain}")


@pytest.mark.asyncio
async def test_record_blocked_delete_exception_is_swallowed():
    """
    Line 84: `pass` in the except block — if r.delete raises, the exception
    is silently swallowed and execution continues normally.
    """
    registry = TransportRegistry(threshold=1)
    fake_r = FakeRedis()
    fake_r.delete = AsyncMock(side_effect=Exception("Redis error"))
    registry._redis = fake_r

    domain = "flaky.com"

    # Should not raise even though r.delete raises
    await registry.record_blocked(domain)

    # delete was still called
    fake_r.delete.assert_awaited_once_with(f"blocks:{domain}")


@pytest.mark.asyncio
async def test_record_blocked_no_delete_when_already_at_top_tier():
    """
    When current transport is already 'flaresolverr' (last tier), no promotion
    and no delete occurs.
    """
    registry = TransportRegistry(threshold=1)
    fake_r = FakeRedis()
    registry._redis = fake_r

    domain = "toptier.com"
    # Pre-set transport to the last tier
    fake_r._store[f"transport:{domain}"] = _TIER_ORDER[-1]

    await registry.record_blocked(domain)

    # No delete called since no promotion happened
    assert fake_r.delete.await_count == 0
