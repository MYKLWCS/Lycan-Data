"""
Circuit Breaker — Redis/Dragonfly-backed per-crawler circuit breaker.

Provides persistent circuit breaker state that survives process restarts
and is shared across all worker processes.

States:
  CLOSED    — normal operation, requests pass through
  OPEN      — too many failures, requests blocked immediately
  HALF_OPEN — probing; one test request allowed; success → CLOSED, failure → OPEN

Usage:
    cb = CircuitBreaker(redis_client)
    if await cb.is_open("twitter.com"):
        return CrawlerResult(found=False, error="circuit_open")
    try:
        result = await do_request()
        await cb.record_success("twitter.com")
    except Exception:
        await cb.record_failure("twitter.com")
        raise
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "lycan:cb:"
_KEY_TTL = 86400  # 24h — auto-expire idle circuit breakers

# Defaults — can be overridden per-key
_DEFAULT_FAILURE_THRESHOLD = 5      # failures before OPEN
_DEFAULT_SUCCESS_THRESHOLD = 2      # successes in HALF_OPEN before CLOSED
_DEFAULT_OPEN_DURATION_S = 60       # seconds to stay OPEN before HALF_OPEN
_DEFAULT_HALF_OPEN_TIMEOUT_S = 30   # seconds to stay HALF_OPEN before auto-OPEN


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


def _safe_state(value: str | None) -> CircuitState:
    """Parse a circuit state string, defaulting to CLOSED on invalid/missing values."""
    try:
        return CircuitState(value) if value else CircuitState.CLOSED
    except ValueError:
        logger.debug("CircuitBreaker: unknown state value %r, defaulting to CLOSED", value)
        return CircuitState.CLOSED


class CircuitBreaker:
    """
    Redis/Dragonfly-backed circuit breaker.

    All state is stored in Redis so it is shared across processes and
    survives restarts. Falls back to CLOSED (open circuit) if Redis
    is unavailable.

    Hash key schema: lycan:cb:{key}
      state           — "CLOSED" | "OPEN" | "HALF_OPEN"
      failures        — consecutive failure count
      successes       — consecutive success count in HALF_OPEN
      opened_at       — unix timestamp when circuit opened (float)
      half_opened_at  — unix timestamp when HALF_OPEN started (float)
    """

    def __init__(
        self,
        redis_client=None,
        *,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
        success_threshold: int = _DEFAULT_SUCCESS_THRESHOLD,
        open_duration_s: float = _DEFAULT_OPEN_DURATION_S,
        half_open_timeout_s: float = _DEFAULT_HALF_OPEN_TIMEOUT_S,
    ) -> None:
        self._redis = redis_client
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.open_duration_s = open_duration_s
        self.half_open_timeout_s = half_open_timeout_s

    # ── Public API ────────────────────────────────────────────────────────────

    async def is_open(self, key: str) -> bool:
        """
        Return True if the circuit is OPEN (requests should be blocked).

        Transitions OPEN → HALF_OPEN automatically when open_duration_s has
        elapsed. Transitions HALF_OPEN → OPEN if half_open_timeout_s exceeded.
        """
        state_data = await self._get(key)
        state = _safe_state(state_data.get("state"))
        now = time.time()

        if state == CircuitState.CLOSED:
            return False

        if state == CircuitState.OPEN:
            opened_at = float(state_data.get("opened_at", 0))
            if now - opened_at >= self.open_duration_s:
                # Transition to HALF_OPEN — allow a probe request
                await self._transition(key, CircuitState.HALF_OPEN, half_opened_at=now)
                logger.info("CircuitBreaker %r: OPEN → HALF_OPEN (probe allowed)", key)
                return False  # allow the probe
            return True

        if state == CircuitState.HALF_OPEN:
            half_opened_at = float(state_data.get("half_opened_at", 0))
            if now - half_opened_at >= self.half_open_timeout_s:
                # Timeout in HALF_OPEN → back to OPEN
                await self._transition(key, CircuitState.OPEN, opened_at=now)
                logger.warning(
                    "CircuitBreaker %r: HALF_OPEN timed out → OPEN", key
                )
                return True
            return False  # allow probe

        return False

    async def record_success(self, key: str) -> None:
        """
        Record a successful request.

        CLOSED: resets failure counter.
        HALF_OPEN: increments success counter; closes circuit if threshold met.
        OPEN: no-op (shouldn't be called when OPEN).
        """
        state_data = await self._get(key)
        state = _safe_state(state_data.get("state"))

        if state == CircuitState.HALF_OPEN:
            successes = int(state_data.get("successes", 0)) + 1
            if successes >= self.success_threshold:
                await self._transition(key, CircuitState.CLOSED)
                logger.info(
                    "CircuitBreaker %r: HALF_OPEN → CLOSED (%d successes)",
                    key, successes,
                )
            else:
                await self._set_field(key, "successes", str(successes))
        else:
            # Reset failure counter on success
            await self._set_field(key, "failures", "0")

    async def record_failure(self, key: str) -> None:
        """
        Record a failed request.

        CLOSED: increments failure counter; opens circuit if threshold met.
        HALF_OPEN: opens circuit immediately.
        OPEN: increments failure counter (used for metrics).
        """
        state_data = await self._get(key)
        state = _safe_state(state_data.get("state"))
        now = time.time()

        if state == CircuitState.HALF_OPEN:
            await self._transition(key, CircuitState.OPEN, opened_at=now)
            logger.warning(
                "CircuitBreaker %r: HALF_OPEN → OPEN (probe failed)", key
            )
            return

        failures = int(state_data.get("failures", 0)) + 1
        await self._set_field(key, "failures", str(failures))

        if state == CircuitState.CLOSED and failures >= self.failure_threshold:
            await self._transition(key, CircuitState.OPEN, opened_at=now)
            logger.warning(
                "CircuitBreaker %r: CLOSED → OPEN (%d failures)", key, failures
            )

    async def get_state(self, key: str) -> dict[str, Any]:
        """Return the full circuit state dict for a key."""
        data = await self._get(key)
        return {
            "key": key,
            "state": data.get("state", CircuitState.CLOSED),
            "failures": int(data.get("failures", 0)),
            "successes": int(data.get("successes", 0)),
            "opened_at": float(data.get("opened_at", 0)),
            "half_opened_at": float(data.get("half_opened_at", 0)),
        }

    async def force_close(self, key: str) -> None:
        """Manually force a circuit to CLOSED state (for ops/recovery)."""
        await self._transition(key, CircuitState.CLOSED)
        logger.info("CircuitBreaker %r: manually forced to CLOSED", key)

    async def force_open(self, key: str) -> None:
        """Manually force a circuit to OPEN state (for ops/maintenance)."""
        await self._transition(key, CircuitState.OPEN, opened_at=time.time())
        logger.info("CircuitBreaker %r: manually forced to OPEN", key)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get(self, key: str) -> dict[str, str]:
        """Return the raw hash data for a circuit breaker key."""
        if self._redis is None:
            return {}
        try:
            data = await self._redis.hgetall(f"{_KEY_PREFIX}{key}")
            if not data:
                return {}
            # Normalize bytes → str
            return {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in data.items()
            }
        except Exception as exc:
            logger.debug("CircuitBreaker._get error key=%r: %s", key, exc)
            return {}

    async def _set_field(self, key: str, field: str, value: str) -> None:
        """Set a single field in the circuit breaker hash."""
        if self._redis is None:
            return
        try:
            redis_key = f"{_KEY_PREFIX}{key}"
            await self._redis.hset(redis_key, field, value)
            await self._redis.expire(redis_key, _KEY_TTL)
        except Exception as exc:
            logger.debug("CircuitBreaker._set_field error key=%r: %s", key, exc)

    async def _transition(self, key: str, state: CircuitState, **extra_fields) -> None:
        """Atomically transition to a new state, resetting counters."""
        if self._redis is None:
            return
        try:
            redis_key = f"{_KEY_PREFIX}{key}"
            mapping: dict[str, str] = {
                "state": state.value,
                "failures": "0",
                "successes": "0",
            }
            for k, v in extra_fields.items():
                mapping[k] = str(v)
            await self._redis.hset(redis_key, mapping=mapping)
            await self._redis.expire(redis_key, _KEY_TTL)
        except Exception as exc:
            logger.debug("CircuitBreaker._transition error key=%r: %s", key, exc)


# ── Module-level singleton ────────────────────────────────────────────────────

_global_cb: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """Return the global circuit breaker. Call init_circuit_breaker() first."""
    global _global_cb
    if _global_cb is None:
        _global_cb = CircuitBreaker()
    return _global_cb


def init_circuit_breaker(redis_client, **kwargs) -> CircuitBreaker:
    """Initialize (or re-initialize) the global circuit breaker with a Redis client."""
    global _global_cb
    _global_cb = CircuitBreaker(redis_client, **kwargs)
    return _global_cb
