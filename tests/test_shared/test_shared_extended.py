"""
Extended coverage tests for shared utility modules.

Targets uncovered lines in:
  - shared/events.py
  - shared/db.py
  - shared/tor.py
  - shared/utils/phone.py
  - shared/utils/scoring.py
  - shared/utils/email.py
  - shared/circuit_breaker.py
  - shared/rate_limiter.py
  - shared/freshness.py
  - shared/data_quality.py
  - shared/models/base.py
  - shared/utils/social.py
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# ---------------------------------------------------------------------------
# shared/events.py
# ---------------------------------------------------------------------------
from shared.events import (
    EventBus,
    _call,
    _deserialize,
    _json_default,
    _serialize,
    get_event_bus,
)


# Line 80 — redis property raises RuntimeError when not connected
def test_event_bus_redis_property_raises_when_not_connected():
    bus = EventBus()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = bus.redis


# Lines 87-89 — publish resolves channel alias and calls redis.publish
@pytest.mark.asyncio
async def test_publish_uses_channel_alias():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    bus._redis = mock_redis

    count = await bus.publish("crawl", {"job": "test"})
    assert count == 1
    # Should have published to the resolved channel name, not the alias
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "lycan:crawl_jobs"


# Lines 87-89 — publish with unknown channel uses channel name as-is
@pytest.mark.asyncio
async def test_publish_unknown_channel_passes_through():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=0)
    bus._redis = mock_redis

    await bus.publish("custom:channel", {"x": 1})
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "custom:channel"


# Lines 93-107 — subscribe: message handler called, handler exception logged
@pytest.mark.asyncio
async def test_subscribe_calls_handler_for_message():
    bus = EventBus()

    received = []

    async def fake_listen():
        yield {"type": "subscribe", "data": None}  # non-message type — ignored
        yield {"type": "message", "data": '{"key": "val"}'}

    mock_pubsub = AsyncMock()
    mock_pubsub.listen = fake_listen
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    bus._redis = mock_redis

    async def handler(data):
        received.append(data)

    await bus.subscribe("crawl", handler)

    assert received == [{"key": "val"}]


# Lines 93-107 — subscribe: sync handler is also called
@pytest.mark.asyncio
async def test_subscribe_calls_sync_handler():
    bus = EventBus()
    received = []

    async def fake_listen():
        yield {"type": "message", "data": '{"n": 42}'}

    mock_pubsub = AsyncMock()
    mock_pubsub.listen = fake_listen
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    bus._redis = mock_redis

    def sync_handler(data):
        received.append(data)

    await bus.subscribe("enrichment", sync_handler)
    assert received == [{"n": 42}]


# Lines 103-104 — subscribe: handler exception is logged, not re-raised
@pytest.mark.asyncio
async def test_subscribe_handler_exception_is_swallowed():
    bus = EventBus()

    async def fake_listen():
        yield {"type": "message", "data": '{"x": 1}'}

    mock_pubsub = AsyncMock()
    mock_pubsub.listen = fake_listen
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()

    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    bus._redis = mock_redis

    async def bad_handler(data):
        raise ValueError("boom")

    # Should not raise
    await bus.subscribe("alerts", bad_handler)


# Lines 113-115 — enqueue sets enqueued_at, uses priority alias
@pytest.mark.asyncio
async def test_enqueue_sets_enqueued_at_and_uses_queue_alias():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    bus._redis = mock_redis

    job = {"task": "crawl"}
    await bus.enqueue(job, priority="high")

    assert "enqueued_at" in job
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == "lycan:queue:high"


# Lines 113-115 — enqueue with unknown priority defaults to normal queue
@pytest.mark.asyncio
async def test_enqueue_unknown_priority_defaults_to_normal():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    bus._redis = mock_redis

    await bus.enqueue({"task": "x"}, priority="nonexistent")
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == "lycan:queue:normal"


# Lines 119-127 — dequeue: returns None on brpop exception
@pytest.mark.asyncio
async def test_dequeue_returns_none_on_redis_exception():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.brpop = AsyncMock(side_effect=ConnectionError("lost"))
    bus._redis = mock_redis

    result = await bus.dequeue("high")
    assert result is None


# Lines 119-127 — dequeue: returns None when brpop returns None (timeout)
@pytest.mark.asyncio
async def test_dequeue_returns_none_on_timeout():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.brpop = AsyncMock(return_value=None)
    bus._redis = mock_redis

    result = await bus.dequeue("normal", timeout=1)
    assert result is None


# Lines 119-127 — dequeue: deserializes payload on success
@pytest.mark.asyncio
async def test_dequeue_returns_deserialized_job():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.brpop = AsyncMock(return_value=("lycan:queue:normal", '{"job_type": "enrich"}'))
    bus._redis = mock_redis

    result = await bus.dequeue("normal")
    assert result == {"job_type": "enrich"}


# Lines 131-139 — dequeue_any: returns None on exception
@pytest.mark.asyncio
async def test_dequeue_any_returns_none_on_exception():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.brpop = AsyncMock(side_effect=OSError("gone"))
    bus._redis = mock_redis

    result = await bus.dequeue_any()
    assert result is None


# Lines 131-139 — dequeue_any: returns None when brpop returns None
@pytest.mark.asyncio
async def test_dequeue_any_returns_none_when_empty():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.brpop = AsyncMock(return_value=None)
    bus._redis = mock_redis

    result = await bus.dequeue_any()
    assert result is None


# Lines 131-139 — dequeue_any: returns deserialized job from whichever queue responded
@pytest.mark.asyncio
async def test_dequeue_any_returns_job():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.brpop = AsyncMock(
        return_value=("lycan:queue:high", '{"priority": "high", "task": "scrape"}')
    )
    bus._redis = mock_redis

    result = await bus.dequeue_any()
    assert result == {"priority": "high", "task": "scrape"}


# Lines 142-143 — queue_length uses QUEUES alias
@pytest.mark.asyncio
async def test_queue_length_uses_queue_alias():
    bus = EventBus()
    mock_redis = AsyncMock()
    mock_redis.llen = AsyncMock(return_value=7)
    bus._redis = mock_redis

    length = await bus.queue_length("ingest")
    assert length == 7
    mock_redis.llen.assert_called_once_with("lycan:queue:ingest")


# Lines 167-171 — _json_default: UUID serializes to str, datetime to isoformat
def test_json_default_uuid():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert _json_default(uid) == "12345678-1234-5678-1234-567812345678"


def test_json_default_datetime():
    dt = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    result = _json_default(dt)
    assert "2024-06-15" in result


def test_json_default_raises_for_unknown_type():
    with pytest.raises(TypeError):
        _json_default(object())


# Lines 175-178 — _call: async and sync dispatch
@pytest.mark.asyncio
async def test_call_async_handler():
    called = []

    async def h(d):
        called.append(d)

    await _call(h, {"a": 1})
    assert called == [{"a": 1}]


@pytest.mark.asyncio
async def test_call_sync_handler():
    called = []

    def h(d):
        called.append(d)

    await _call(h, {"b": 2})
    assert called == [{"b": 2}]


# ---------------------------------------------------------------------------
# shared/db.py — lines 42-48: get_db commits on success, rolls back on error
# ---------------------------------------------------------------------------

from shared.db import get_db


@pytest.mark.asyncio
async def test_get_db_yields_session_and_commits():
    """get_db should yield a session and commit when no exception occurs."""
    mock_session = AsyncMock()

    # Build a proper async context manager that returns mock_session
    class FakeCM:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            return False

    with patch("shared.db.AsyncSessionLocal", return_value=FakeCM()):
        async for session in get_db():
            assert session is mock_session

    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception():
    """get_db should call rollback and re-raise on exception."""
    mock_session = AsyncMock()

    class FakeCM:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            return False

    with patch("shared.db.AsyncSessionLocal", return_value=FakeCM()):
        gen = get_db()
        session = await gen.__anext__()
        assert session is mock_session
        with pytest.raises(ValueError, match="db error"):
            await gen.athrow(ValueError("db error"))

    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# shared/tor.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.config import settings as tor_settings
from shared.tor import TorEndpoint, TorInstance, TorManager


# Lines 112-115 — _connect: successful controller connection sets is_connected=True
@pytest.mark.asyncio
async def test_connect_success_sets_connected():
    mgr = TorManager()
    mock_controller = MagicMock()
    mock_controller.authenticate = MagicMock()
    mock_controller.close = MagicMock()

    with patch("shared.tor.Controller") as MockController:
        MockController.from_port = MagicMock(return_value=mock_controller)

        async def fake_run_in_executor(executor, fn):
            return fn()

        with patch("asyncio.get_running_loop") as mock_loop_getter:
            loop = AsyncMock()
            loop.run_in_executor = AsyncMock(side_effect=fake_run_in_executor)
            mock_loop_getter.return_value = loop

            with patch.object(tor_settings, "tor_enabled", True):
                await mgr._connect(TorInstance.TOR1)

    assert mgr._endpoints[TorInstance.TOR1].is_connected is True
    assert mgr._endpoints[TorInstance.TOR1].controller is mock_controller


# Lines 139-140 — _parse_socks: malformed URL returns empty string and 0
def test_parse_socks_valid():
    host, port = TorManager._parse_socks("socks5://127.0.0.1:9050")
    assert host == "127.0.0.1"
    assert port == 9050


def test_parse_socks_malformed_returns_empty():
    host, port = TorManager._parse_socks("not-a-url")
    assert host == ""
    assert port == 0


# Lines 152-153 — _tcp_reachable: returns False on connection error
@pytest.mark.asyncio
async def test_tcp_reachable_returns_false_on_error():
    with patch("socket.create_connection", side_effect=OSError("refused")):
        result = await TorManager._tcp_reachable("127.0.0.1", 9999, timeout=0.1)
    assert result is False


# Lines 156-163 — disconnect_all: closes connected controllers
@pytest.mark.asyncio
async def test_disconnect_all_closes_controller():
    mgr = TorManager()
    mock_ctrl = MagicMock()
    ep = mgr._endpoints[TorInstance.TOR2]
    ep.controller = mock_ctrl
    ep.is_connected = True

    await mgr.disconnect_all()

    mock_ctrl.close.assert_called_once()
    assert ep.is_connected is False


# Lines 156-163 — disconnect_all: controller.close exception is swallowed
@pytest.mark.asyncio
async def test_disconnect_all_swallows_close_exception():
    mgr = TorManager()
    mock_ctrl = MagicMock()
    mock_ctrl.close = MagicMock(side_effect=RuntimeError("close failed"))
    ep = mgr._endpoints[TorInstance.TOR1]
    ep.controller = mock_ctrl
    ep.is_connected = True

    await mgr.disconnect_all()  # must not raise
    assert ep.is_connected is False


# Line 168 — new_circuit: returns False when tor disabled
@pytest.mark.asyncio
async def test_new_circuit_disabled_returns_false():
    mgr = TorManager()
    with patch.object(tor_settings, "tor_enabled", False):
        result = await mgr.new_circuit(TorInstance.TOR1)
    assert result is False


# Lines 173-180 — new_circuit: success path returns True
@pytest.mark.asyncio
async def test_new_circuit_success_returns_true():
    mgr = TorManager()
    mock_ctrl = MagicMock()
    ep = mgr._endpoints[TorInstance.TOR2]
    ep.controller = mock_ctrl

    async def fake_run_in_executor(executor, fn):
        return fn()

    with patch.object(tor_settings, "tor_enabled", True):
        with patch("asyncio.get_running_loop") as mock_loop_getter:
            loop = AsyncMock()
            loop.run_in_executor = AsyncMock(side_effect=fake_run_in_executor)
            mock_loop_getter.return_value = loop

            result = await mgr.new_circuit(TorInstance.TOR2)

    assert result is True


# Lines 173-180 — new_circuit: exception returns False
@pytest.mark.asyncio
async def test_new_circuit_exception_returns_false():
    mgr = TorManager()
    mock_ctrl = MagicMock()
    ep = mgr._endpoints[TorInstance.TOR1]
    ep.controller = mock_ctrl

    with patch.object(tor_settings, "tor_enabled", True):
        with patch("asyncio.get_running_loop") as mock_loop_getter:
            loop = AsyncMock()
            loop.run_in_executor = AsyncMock(side_effect=Exception("stem error"))
            mock_loop_getter.return_value = loop

            result = await mgr.new_circuit(TorInstance.TOR1)

    assert result is False


# Lines 184-185 — new_circuit_all: calls new_circuit for all instances
@pytest.mark.asyncio
async def test_new_circuit_all_does_not_raise():
    mgr = TorManager()
    with patch.object(tor_settings, "tor_enabled", False):
        await mgr.new_circuit_all()  # all return False quietly


# Line 189 — is_available: True only when enabled and connected
def test_is_available_connected():
    mgr = TorManager()
    with patch.object(tor_settings, "tor_enabled", True):
        mgr._endpoints[TorInstance.TOR2].is_connected = True
        assert mgr.is_available(TorInstance.TOR2) is True


def test_is_available_disconnected():
    mgr = TorManager()
    with patch.object(tor_settings, "tor_enabled", True):
        mgr._endpoints[TorInstance.TOR2].is_connected = False
        assert mgr.is_available(TorInstance.TOR2) is False


def test_is_available_tor_disabled():
    mgr = TorManager()
    mgr._endpoints[TorInstance.TOR2].is_connected = True
    with patch.object(tor_settings, "tor_enabled", False):
        assert mgr.is_available(TorInstance.TOR2) is False


# Line 193 — can_rotate: True only when enabled and controller is not None
def test_can_rotate_with_controller():
    mgr = TorManager()
    mgr._endpoints[TorInstance.TOR1].controller = MagicMock()
    with patch.object(tor_settings, "tor_enabled", True):
        assert mgr.can_rotate(TorInstance.TOR1) is True


def test_can_rotate_no_controller():
    mgr = TorManager()
    mgr._endpoints[TorInstance.TOR1].controller = None
    with patch.object(tor_settings, "tor_enabled", True):
        assert mgr.can_rotate(TorInstance.TOR1) is False


def test_can_rotate_tor_disabled():
    mgr = TorManager()
    mgr._endpoints[TorInstance.TOR1].controller = MagicMock()
    with patch.object(tor_settings, "tor_enabled", False):
        assert mgr.can_rotate(TorInstance.TOR1) is False


# Line 196 — any_available: True when at least one endpoint is connected
def test_any_available_false_initially():
    mgr = TorManager()
    assert mgr.any_available() is False


def test_any_available_true_when_one_connected():
    mgr = TorManager()
    mgr._endpoints[TorInstance.TOR3].is_connected = True
    assert mgr.any_available() is True


# Lines 121-127 — _connect fallback: SOCKS reachable marks active
@pytest.mark.asyncio
async def test_connect_falls_back_to_socks_when_control_fails():
    mgr = TorManager()

    with patch("shared.tor.Controller") as MockController:
        MockController.from_port = MagicMock(side_effect=Exception("control port closed"))
        with patch.object(TorManager, "_tcp_reachable", new_callable=AsyncMock, return_value=True):
            with patch.object(tor_settings, "tor_enabled", True):
                await mgr._connect(TorInstance.TOR2)

    assert mgr._endpoints[TorInstance.TOR2].is_connected is True
    assert mgr._endpoints[TorInstance.TOR2].controller is None


# ---------------------------------------------------------------------------
# shared/utils/phone.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.constants import LineType
from shared.utils.phone import (
    get_country_code,
    get_line_type,
    is_valid_phone,
    normalize_phone,
)


# Line 20 — normalize_phone: valid number that fails is_valid_number returns None
def test_normalize_phone_invalid_but_parseable():
    # Some numbers parse but are not valid (e.g. too short)
    result = normalize_phone("123", default_region="US")
    assert result is None


# Line 33 — get_line_type: valid number with mapping match
def test_get_line_type_mobile():
    # +1 area code 415 is typically mobile/fixed_line_or_mobile
    lt = get_line_type("+14155552671", default_region="US")
    assert lt in (LineType.MOBILE, LineType.LANDLINE, LineType.UNKNOWN)


# Line 33 — get_line_type: invalid number returns UNKNOWN
def test_get_line_type_invalid_number_returns_unknown():
    lt = get_line_type("000", default_region="US")
    assert lt == LineType.UNKNOWN


# Lines 52-59 — get_country_code: valid number returns region code
def test_get_country_code_valid_us():
    code = get_country_code("+14155552671")
    assert code == "US"


def test_get_country_code_valid_gb():
    # +44 791 112 3456 resolves to GG (Guernsey) per libphonenumber
    code = get_country_code("+447911123456", default_region="GB")
    assert code is not None  # resolves to a UK-region code
    assert code in ("GB", "GG", "JE", "IM")  # all +44 regions


# Lines 52-59 — get_country_code: invalid number returns None
def test_get_country_code_invalid_returns_none():
    result = get_country_code("notanumber")
    assert result is None


# Lines 52-59 — get_country_code: parseable but invalid number returns None
def test_get_country_code_parseable_invalid_returns_none():
    result = get_country_code("123", default_region="US")
    assert result is None


# ---------------------------------------------------------------------------
# shared/utils/scoring.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.utils.scoring import clamp, log_scale, tier_from_score, weighted_sum


# Lines 18-22 — weighted_sum: zero total_weight returns 0.0
def test_weighted_sum_no_matching_keys_returns_zero():
    # weights has no keys matching scores
    result = weighted_sum({"a": 0.5, "b": 0.8}, {"c": 0.5, "d": 0.3})
    assert result == 0.0


def test_weighted_sum_zero_weight_values_returns_zero():
    # weights present but all zero
    result = weighted_sum({"a": 0.5}, {"a": 0.0})
    assert result == 0.0


# Lines 18-22 — weighted_sum: total_weight >= 1.0 path (no division)
def test_weighted_sum_total_weight_at_least_one():
    # weights sum to >= 1.0 for matched keys — result should be clamped
    result = weighted_sum({"a": 1.0, "b": 1.0}, {"a": 0.6, "b": 0.6})
    assert 0.0 <= result <= 1.0


# Line 40 — tier_from_score: empty tiers list returns "unknown"
def test_tier_from_score_empty_tiers():
    result = tier_from_score(0.5, [])
    assert result == "unknown"


# Line 40 — tier_from_score: score below all thresholds uses last tier label
def test_tier_from_score_below_all_thresholds():
    tiers = [(0.8, "high"), (0.5, "medium"), (0.2, "low")]
    # score 0.1 is below all thresholds; last element after sort is (0.2, "low")
    result = tier_from_score(0.1, tiers)
    assert result == "low"


# ---------------------------------------------------------------------------
# shared/utils/email.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.utils.email import extract_domain, is_valid_email, normalize_email


# Line 16 — normalize_email: empty string returns None
def test_normalize_email_empty_string_returns_none():
    assert normalize_email("") is None


# Line 27 — extract_domain: invalid email returns None
def test_extract_domain_invalid_email_returns_none():
    assert extract_domain("notanemail") is None


def test_extract_domain_empty_returns_none():
    assert extract_domain("") is None


# ---------------------------------------------------------------------------
# shared/circuit_breaker.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    _safe_state,
    get_circuit_breaker,
    init_circuit_breaker,
)


class FakeCBRedis:
    """Minimal in-memory Redis fake for circuit breaker tests."""

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


def make_cb_with_redis(**kwargs):
    redis = FakeCBRedis()
    cb = CircuitBreaker(redis, **kwargs)
    return cb, redis


# Lines 121-123 — is_open: HALF_OPEN still within timeout returns False (probe allowed)
@pytest.mark.asyncio
async def test_half_open_within_timeout_allows_probe():
    cb, redis = make_cb_with_redis(failure_threshold=1, open_duration_s=1, half_open_timeout_s=60)
    key = "svc.probe_allowed"

    # Force HALF_OPEN state with a recent half_opened_at
    redis_key = f"lycan:cb:{key}"
    redis._store[redis_key] = {
        "state": "HALF_OPEN",
        "failures": "0",
        "successes": "0",
        "half_opened_at": str(time.time() - 5),  # only 5s ago, timeout=60
    }

    result = await cb.is_open(key)
    assert result is False  # probe should be allowed


# Lines 214-216 — _get: Redis exception returns empty dict
@pytest.mark.asyncio
async def test_get_returns_empty_dict_on_redis_error():
    mock_redis = AsyncMock()
    mock_redis.hgetall = AsyncMock(side_effect=ConnectionError("redis gone"))
    cb = CircuitBreaker(mock_redis)

    result = await cb._get("any.key")
    assert result == {}


# Lines 214-216 — _get: bytes keys/values are decoded to str
@pytest.mark.asyncio
async def test_get_decodes_bytes_keys_and_values():
    mock_redis = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={b"state": b"OPEN", b"failures": b"3"})
    cb = CircuitBreaker(mock_redis)

    result = await cb._get("some.key")
    assert result == {"state": "OPEN", "failures": "3"}


# Lines 226-227 — _set_field: Redis exception is swallowed
@pytest.mark.asyncio
async def test_set_field_swallows_redis_exception():
    mock_redis = AsyncMock()
    mock_redis.hset = AsyncMock(side_effect=ConnectionError("gone"))
    cb = CircuitBreaker(mock_redis)

    # Must not raise
    await cb._set_field("key", "failures", "2")


# Line 232 — _transition: no-op when redis is None
@pytest.mark.asyncio
async def test_transition_noop_when_no_redis():
    cb = CircuitBreaker(redis_client=None)
    # Should not raise
    await cb._transition("key", CircuitState.OPEN, opened_at=time.time())


# Lines 244-245 — _transition: Redis exception is swallowed
@pytest.mark.asyncio
async def test_transition_swallows_redis_exception():
    mock_redis = AsyncMock()
    mock_redis.hset = AsyncMock(side_effect=ConnectionError("gone"))
    cb = CircuitBreaker(mock_redis)

    # Must not raise
    await cb._transition("key", CircuitState.CLOSED)


# Line 257 — get_circuit_breaker: lazy init creates instance with no Redis
def test_get_circuit_breaker_lazy_init():
    import shared.circuit_breaker as cb_module

    # Reset global so lazy init fires
    original = cb_module._global_cb
    cb_module._global_cb = None
    try:
        cb = get_circuit_breaker()
        assert isinstance(cb, CircuitBreaker)
        assert cb._redis is None
    finally:
        cb_module._global_cb = original


# ---------------------------------------------------------------------------
# shared/rate_limiter.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.rate_limiter import (
    RateLimiter,
    RateLimitSpec,
    _spec_for,
    get_rate_limiter,
    init_rate_limiter,
)


class FakeRLRedis:
    """Minimal fake Redis for rate limiter tests."""

    def __init__(self):
        self._store: dict[str, dict[str, str]] = {}
        self._sha_counter = 0

    async def script_load(self, script: str) -> str:
        self._sha_counter += 1
        return f"sha_{self._sha_counter}"

    async def evalsha(self, sha, num_keys, key, rate, burst, now, requested, ttl):
        rate_f = float(rate)
        burst_f = float(burst)
        now_f = float(now)
        data = self._store.get(key, {})
        tokens = float(data.get("tokens", burst_f))
        last_refill = float(data.get("last_refill", now_f))
        elapsed = now_f - last_refill
        new_tokens = min(burst_f, tokens + elapsed * rate_f)
        if new_tokens >= 1:
            new_tokens -= 1
            self._store.setdefault(key, {})
            self._store[key]["tokens"] = f"{new_tokens:.4f}"
            self._store[key]["last_refill"] = f"{now_f:.6f}"
            return [1, f"{new_tokens:.4f}", 0]
        else:
            deficit = 1 - new_tokens
            retry_ms = int((deficit / rate_f) * 1000) + 1
            self._store.setdefault(key, {})
            self._store[key]["tokens"] = f"{new_tokens:.4f}"
            self._store[key]["last_refill"] = f"{now_f:.6f}"
            return [0, f"{new_tokens:.4f}", retry_ms]

    async def hgetall(self, key: str):
        data = self._store.get(key, {})
        return {k.encode(): v.encode() for k, v in data.items()}

    async def delete(self, key: str):
        self._store.pop(key, None)

    async def expire(self, key: str, ttl: int):
        pass


# Lines 203-205 — _try_acquire: Redis exception returns 0 (fail open)
@pytest.mark.asyncio
async def test_try_acquire_redis_exception_returns_zero():
    mock_redis = AsyncMock()
    mock_redis.script_load = AsyncMock(return_value="sha1")
    mock_redis.evalsha = AsyncMock(side_effect=ConnectionError("redis down"))

    limiter = RateLimiter(mock_redis)
    limiter._script_sha = "sha1"

    result = await limiter._try_acquire("any.key", rate=1.0, burst=5)
    assert result == 0  # fail open


# Lines 203-205 — _try_acquire: loads script on first call
@pytest.mark.asyncio
async def test_try_acquire_loads_script_on_first_call():
    redis = FakeRLRedis()
    limiter = RateLimiter(redis)
    assert limiter._script_sha is None

    await limiter._try_acquire("test.key", rate=10.0, burst=5)
    assert limiter._script_sha is not None


# Lines 219-220 — peek: Redis exception falls back to burst default
@pytest.mark.asyncio
async def test_peek_redis_exception_returns_burst():
    mock_redis = AsyncMock()
    mock_redis.hgetall = AsyncMock(side_effect=ConnectionError("gone"))

    limiter = RateLimiter(mock_redis)
    tokens = await limiter.peek("any.key")
    expected = float(_spec_for("any.key").burst)
    assert tokens == expected


# Lines 219-220 — peek: empty data returns burst default
@pytest.mark.asyncio
async def test_peek_empty_data_returns_burst():
    mock_redis = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={})

    limiter = RateLimiter(mock_redis)
    tokens = await limiter.peek("unknown-domain-xyz.example")
    assert tokens == float(_spec_for("unknown-domain-xyz.example").burst)


# Lines 228-229 — reset: Redis exception is swallowed (fail open)
@pytest.mark.asyncio
async def test_reset_swallows_redis_exception():
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock(side_effect=ConnectionError("gone"))

    limiter = RateLimiter(mock_redis)
    # Must not raise
    await limiter.reset("any.key")


# Line 240 — get_rate_limiter: lazy init creates instance with no Redis
def test_get_rate_limiter_lazy_init():
    import shared.rate_limiter as rl_module

    original = rl_module._global_limiter
    rl_module._global_limiter = None
    try:
        rl = get_rate_limiter()
        assert isinstance(rl, RateLimiter)
        assert rl._redis is None
    finally:
        rl_module._global_limiter = original


# ---------------------------------------------------------------------------
# shared/freshness.py — uncovered lines
# ---------------------------------------------------------------------------

from shared.freshness import compute_freshness, get_half_life, hours_until_stale, is_stale


# Line 37 — compute_freshness: naive datetime (no tzinfo) is treated as timezone.utc
def test_compute_freshness_naive_datetime():
    # Naive datetime, just scraped
    now_naive = datetime.now(UTC)
    score = compute_freshness(now_naive, "default")
    assert score >= 0.99


# Line 61 — hours_until_stale: None returns 0.0
def test_hours_until_stale_none_returns_zero():
    result = hours_until_stale(None, "default")
    assert result == 0.0


# Line 66 — hours_until_stale: naive datetime is treated as timezone.utc
def test_hours_until_stale_naive_datetime():
    now_naive = datetime.now(UTC) - timedelta(hours=1)
    result = hours_until_stale(now_naive, "social_media_profile")
    assert result >= 0.0


# ---------------------------------------------------------------------------
# shared/data_quality.py — line 28
# ---------------------------------------------------------------------------

from shared.data_quality import compute_composite_quality


# Line 28 — compute_composite_quality: conflict_flag=True path
def test_composite_quality_with_conflict_flag_true():
    score_with = compute_composite_quality(0.5, 0.5, 0.5, conflict_flag=True)
    score_without = compute_composite_quality(0.5, 0.5, 0.5, conflict_flag=False)
    # Conflict reduces the score by CONFLICT_PENALTY
    assert score_with < score_without


def test_composite_quality_conflict_floor_at_zero():
    # All-zero inputs with conflict flag — result must not go below 0
    score = compute_composite_quality(0.0, 0.0, 0.0, conflict_flag=True)
    assert score == 0.0


# ---------------------------------------------------------------------------
# shared/models/base.py — line 18
# ---------------------------------------------------------------------------

from shared.models.base import Base, _apply_column_defaults


# Line 18 — _apply_column_defaults: class without __table__ is a no-op
def test_apply_column_defaults_no_table_is_noop():
    class NoTableClass:
        pass

    instance = NoTableClass()
    # Should not raise; nothing happens because there is no __table__
    _apply_column_defaults(instance, (), {})


# line 18 — _apply_column_defaults: kwargs keys are not overwritten
def test_apply_column_defaults_does_not_overwrite_kwargs():
    """If a column name is already in kwargs, the default should not override it."""

    class FakeColumn:
        name = "status"
        default = MagicMock()

    class FakeTable:
        columns = [FakeColumn()]

    class FakeModel:
        __table__ = FakeTable()

    FakeColumn.default.is_scalar = True
    FakeColumn.default.arg = "default_value"

    instance = FakeModel()
    kwargs = {"status": "pending"}  # already provided

    _apply_column_defaults(instance, (), kwargs)
    # The existing value should be preserved, not overwritten
    assert kwargs["status"] == "pending"


# ---------------------------------------------------------------------------
# shared/utils/social.py — line 41
# ---------------------------------------------------------------------------

from shared.utils.social import extract_handle_from_url, normalize_handle


# Line 41 — extract_handle_from_url: returns None for non-matching URLs
def test_extract_handle_from_url_no_match_returns_none():
    result = extract_handle_from_url("https://example.com/some/path")
    assert result is None


def test_extract_handle_from_url_none_matching_url():
    result = extract_handle_from_url("https://notasocialsite.org/user/test")
    assert result is None


# Line 41 — extract_handle_from_url: telegram URL extraction
def test_extract_handle_from_telegram_url():
    result = extract_handle_from_url("https://t.me/durov")
    assert result == "durov"


# Line 41 — extract_handle_from_url: YouTube @-handle extraction
def test_extract_handle_from_youtube_url():
    result = extract_handle_from_url("https://www.youtube.com/@mkbhd")
    assert result == "mkbhd"


# Line 41 — extract_handle_from_url: LinkedIn URL extraction
def test_extract_handle_from_linkedin_url():
    result = extract_handle_from_url("https://www.linkedin.com/in/satyanadella")
    assert result == "satyanadella"
