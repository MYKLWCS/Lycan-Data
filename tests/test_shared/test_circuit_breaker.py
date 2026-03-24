"""
Tests for shared/circuit_breaker.py

All tests use an in-memory fake Redis — no real infrastructure required.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    _safe_state,
    get_circuit_breaker,
    init_circuit_breaker,
)


# ── Fake Redis ────────────────────────────────────────────────────────────────


class FakeRedis:
    """Minimal in-memory Redis fake supporting hgetall, hset, expire."""

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
        pass  # no-op for tests

    async def delete(self, key: str):
        self._store.pop(key, None)


def make_cb(**kwargs) -> tuple[CircuitBreaker, FakeRedis]:
    redis = FakeRedis()
    cb = CircuitBreaker(redis, **kwargs)
    return cb, redis


# ── _safe_state helper ────────────────────────────────────────────────────────


def test_safe_state_defaults_to_closed_on_none():
    assert _safe_state(None) == CircuitState.CLOSED


def test_safe_state_defaults_to_closed_on_garbage():
    assert _safe_state("BOGUS") == CircuitState.CLOSED


def test_safe_state_parses_valid_states():
    assert _safe_state("CLOSED") == CircuitState.CLOSED
    assert _safe_state("OPEN") == CircuitState.OPEN
    assert _safe_state("HALF_OPEN") == CircuitState.HALF_OPEN


# ── Circuit starts CLOSED ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_starts_closed():
    cb, _ = make_cb()
    assert await cb.is_open("example.com") is False


@pytest.mark.asyncio
async def test_get_state_defaults():
    cb, _ = make_cb()
    state = await cb.get_state("example.com")
    assert state["state"] == CircuitState.CLOSED
    assert state["failures"] == 0
    assert state["successes"] == 0


# ── CLOSED → OPEN after failure threshold ─────────────────────────────────────


@pytest.mark.asyncio
async def test_closed_to_open_after_failures():
    cb, _ = make_cb(failure_threshold=3)
    key = "svc.test"

    # Below threshold — still closed
    await cb.record_failure(key)
    await cb.record_failure(key)
    assert await cb.is_open(key) is False

    # Hit threshold — now OPEN
    await cb.record_failure(key)
    assert await cb.is_open(key) is True


@pytest.mark.asyncio
async def test_failure_counter_resets_on_success():
    cb, _ = make_cb(failure_threshold=3)
    key = "svc.reset"

    await cb.record_failure(key)
    await cb.record_failure(key)
    await cb.record_success(key)  # reset counter

    # Third failure after reset should NOT open (counter was cleared)
    await cb.record_failure(key)
    assert await cb.is_open(key) is False


# ── OPEN rejects calls immediately ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_circuit_blocks_immediately():
    # Tight timeout so OPEN → HALF_OPEN won't trigger during this test
    cb, _ = make_cb(failure_threshold=1, open_duration_s=9999)
    key = "svc.blocked"

    await cb.record_failure(key)
    assert await cb.is_open(key) is True


@pytest.mark.asyncio
async def test_force_open():
    cb, _ = make_cb()
    key = "svc.force_open"
    await cb.force_open(key)
    state = await cb.get_state(key)
    assert state["state"] == CircuitState.OPEN


# ── OPEN → HALF_OPEN after timeout ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_transitions_to_half_open_after_duration():
    cb, redis = make_cb(failure_threshold=1, open_duration_s=10)
    key = "svc.half_open"

    await cb.record_failure(key)
    # Manually backdate opened_at so the timeout has already elapsed
    redis_key = f"lycan:cb:{key}"
    redis._store[redis_key]["opened_at"] = str(time.time() - 11)

    # is_open should now see elapsed > open_duration_s and transition
    result = await cb.is_open(key)
    assert result is False  # probe request allowed

    state = await cb.get_state(key)
    assert state["state"] == CircuitState.HALF_OPEN


# ── HALF_OPEN → CLOSED on success ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_half_open_to_closed_on_sufficient_successes():
    cb, redis = make_cb(failure_threshold=1, open_duration_s=10, success_threshold=2)
    key = "svc.recover"

    # Get the circuit into HALF_OPEN
    await cb.record_failure(key)
    redis_key = f"lycan:cb:{key}"
    redis._store[redis_key]["opened_at"] = str(time.time() - 11)
    await cb.is_open(key)  # triggers OPEN → HALF_OPEN

    assert (await cb.get_state(key))["state"] == CircuitState.HALF_OPEN

    # First success — not enough yet
    await cb.record_success(key)
    assert (await cb.get_state(key))["state"] == CircuitState.HALF_OPEN

    # Second success — closes the circuit
    await cb.record_success(key)
    assert (await cb.get_state(key))["state"] == CircuitState.CLOSED


# ── HALF_OPEN → OPEN on failure ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_half_open_to_open_on_failure():
    cb, redis = make_cb(failure_threshold=1, open_duration_s=10)
    key = "svc.probe_fail"

    await cb.record_failure(key)
    redis_key = f"lycan:cb:{key}"
    redis._store[redis_key]["opened_at"] = str(time.time() - 11)
    await cb.is_open(key)  # OPEN → HALF_OPEN

    assert (await cb.get_state(key))["state"] == CircuitState.HALF_OPEN

    # Probe fails — should go back to OPEN
    await cb.record_failure(key)
    assert (await cb.get_state(key))["state"] == CircuitState.OPEN


# ── HALF_OPEN timeout → OPEN ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_half_open_timeout_returns_to_open():
    cb, redis = make_cb(failure_threshold=1, open_duration_s=10, half_open_timeout_s=5)
    key = "svc.half_timeout"

    await cb.record_failure(key)
    redis_key = f"lycan:cb:{key}"
    redis._store[redis_key]["opened_at"] = str(time.time() - 11)
    await cb.is_open(key)  # OPEN → HALF_OPEN

    # Backdate half_opened_at so timeout has elapsed
    redis._store[redis_key]["half_opened_at"] = str(time.time() - 6)

    result = await cb.is_open(key)
    assert result is True  # back to OPEN due to timeout

    state = await cb.get_state(key)
    assert state["state"] == CircuitState.OPEN


# ── Reset / force_close ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_close_resets_open_circuit():
    cb, _ = make_cb(failure_threshold=1, open_duration_s=9999)
    key = "svc.manual_reset"

    await cb.record_failure(key)
    assert await cb.is_open(key) is True

    await cb.force_close(key)
    assert await cb.is_open(key) is False
    assert (await cb.get_state(key))["state"] == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_force_close_resets_counters():
    cb, _ = make_cb(failure_threshold=5)
    key = "svc.counter_reset"

    await cb.record_failure(key)
    await cb.record_failure(key)
    await cb.force_close(key)

    state = await cb.get_state(key)
    assert state["failures"] == 0
    assert state["successes"] == 0


# ── No Redis — falls back gracefully ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_redis_always_closed():
    cb = CircuitBreaker(redis_client=None)
    assert await cb.is_open("anything") is False


@pytest.mark.asyncio
async def test_no_redis_record_failure_noop():
    cb = CircuitBreaker(redis_client=None)
    # Should not raise
    await cb.record_failure("anything")
    await cb.record_success("anything")


# ── Module-level singleton ────────────────────────────────────────────────────


def test_get_circuit_breaker_returns_instance():
    cb = get_circuit_breaker()
    assert isinstance(cb, CircuitBreaker)


def test_init_circuit_breaker_replaces_global():
    redis = FakeRedis()
    cb = init_circuit_breaker(redis)
    assert isinstance(cb, CircuitBreaker)
    assert cb._redis is redis
    # Subsequent get_circuit_breaker returns the initialized instance
    assert get_circuit_breaker() is cb
