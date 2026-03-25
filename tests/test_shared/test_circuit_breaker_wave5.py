"""
test_circuit_breaker_wave5.py — Coverage gap tests for shared/circuit_breaker.py.

Targets:
  - Line 123: return False — the final return at the end of is_open(),
    reached when state is HALF_OPEN and half_open_timeout_s has NOT elapsed yet
    (i.e., the probe window is still open).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.circuit_breaker import CircuitBreaker, CircuitState


# ---------------------------------------------------------------------------
# Fake Redis (mirrors pattern in test_circuit_breaker.py)
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self):
        self._store: dict[str, dict[str, str]] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._store.get(key, {}))

    async def hset(self, key: str, field=None, value=None, mapping=None):
        if key not in self._store:
            self._store[key] = {}
        if mapping is not None:
            for k, v in mapping.items():
                self._store[key][str(k)] = str(v)
        elif field is not None:
            self._store[key][str(field)] = str(value)

    async def expire(self, key: str, ttl: int):
        pass

    async def delete(self, key: str):
        self._store.pop(key, None)


def make_cb(**kwargs) -> tuple[CircuitBreaker, FakeRedis]:
    r = FakeRedis()
    cb = CircuitBreaker(r, **kwargs)
    return cb, r


# ---------------------------------------------------------------------------
# Line 123: return False — HALF_OPEN state, probe window still open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_open_half_open_within_timeout_returns_false():
    """
    Line 123: When the circuit is HALF_OPEN and half_open_timeout_s has not
    elapsed, is_open() must return False (allow the probe).
    The final `return False` at line 123 is the fall-through after the
    HALF_OPEN timeout check fails.
    """
    cb, r = make_cb(half_open_timeout_s=3600.0)  # very long timeout — never expires during test

    key = "test-domain"
    now = time.time()

    # Manually put the circuit into HALF_OPEN state with a recent half_opened_at
    r._store[f"lycan:cb:{key}"] = {
        "state": CircuitState.HALF_OPEN,
        "half_opened_at": str(now),  # just entered HALF_OPEN — timeout nowhere near
    }

    result = await cb.is_open(key)

    # Should be False — probe is allowed (within timeout, no block)
    assert result is False


@pytest.mark.asyncio
async def test_is_open_half_open_timed_out_returns_true():
    """
    Line 120: HALF_OPEN timeout elapsed → transitions back to OPEN → returns True.
    (Complementary to line 123 test; ensures both branches in the HALF_OPEN block
    are covered.)
    """
    cb, r = make_cb(half_open_timeout_s=1.0)

    key = "timed-out-domain"
    old_time = time.time() - 100.0  # way past the timeout

    r._store[f"lycan:cb:{key}"] = {
        "state": CircuitState.HALF_OPEN,
        "half_opened_at": str(old_time),
    }

    result = await cb.is_open(key)

    # Timed out → back to OPEN → blocked
    assert result is True


@pytest.mark.asyncio
async def test_is_open_half_open_probe_window_exact_boundary():
    """
    Line 123: Probe window is active (just barely within timeout).
    """
    cb, r = make_cb(half_open_timeout_s=60.0)

    key = "boundary-domain"
    # Set half_opened_at to 1 second ago — well within 60s timeout
    r._store[f"lycan:cb:{key}"] = {
        "state": CircuitState.HALF_OPEN,
        "half_opened_at": str(time.time() - 1.0),
    }

    result = await cb.is_open(key)
    assert result is False
