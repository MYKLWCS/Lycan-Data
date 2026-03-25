"""
test_shared_transport_wave3.py — Coverage gaps for:

1. shared/transport_registry.py
   Lines 37-38: _get_redis exception → _redis = None
   Lines 47-49: get_transport Redis hit (val.decode())
   Lines 57-59: set_transport Redis hit
   Lines 67-71: record_blocked in-memory fallback (no Redis)

2. shared/health.py
   Line 20:    _check_flaresolverr returns True (200 response)
   Lines 30-31: _check_tor returns True (200 + IsTor=True)
   Lines 44-45: _check_dragonfly returns True (ping succeeds)

All network/Redis I/O is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.transport_registry import TransportRegistry


# ===========================================================================
# shared/transport_registry.py
# ===========================================================================


class TestTransportRegistryRedis:
    """Tests for Redis-backed paths (lines 37-38, 47-49, 57-59)."""

    @pytest.mark.asyncio
    async def test_get_redis_exception_returns_none(self):
        """Redis connect/ping raises → _redis is set to None (lines 37-38)."""
        reg = TransportRegistry()

        import sys
        import types

        # Build a fake redis.asyncio module that raises on from_url
        fake_aioredis = types.ModuleType("redis.asyncio")
        fake_aioredis.from_url = MagicMock(side_effect=OSError("redis unavailable"))

        fake_redis = types.ModuleType("redis")
        fake_redis.asyncio = fake_aioredis
        sys.modules["redis"] = fake_redis
        sys.modules["redis.asyncio"] = fake_aioredis

        try:
            r = await reg._get_redis()
        finally:
            # Restore real redis if it was there
            sys.modules.pop("redis", None)
            sys.modules.pop("redis.asyncio", None)
            try:
                import redis as real_redis
                sys.modules["redis"] = real_redis
                sys.modules["redis.asyncio"] = real_redis.asyncio
            except ImportError:
                pass

        assert r is None
        assert reg._redis is None

    @pytest.mark.asyncio
    async def test_get_transport_redis_hit_decodes_value(self):
        """Redis has a value → val.decode() returned (lines 47-48)."""
        reg = TransportRegistry()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"curl")
        mock_redis.ping = AsyncMock(return_value=True)
        reg._redis = mock_redis

        result = await reg.get_transport("blocked.com")

        assert result == "curl"

    @pytest.mark.asyncio
    async def test_get_transport_redis_miss_returns_httpx(self):
        """Redis returns None → fallback to 'httpx' (line 46, else branch of 'val')."""
        reg = TransportRegistry()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.ping = AsyncMock(return_value=True)
        reg._redis = mock_redis

        result = await reg.get_transport("unknown.com")

        assert result == "httpx"

    @pytest.mark.asyncio
    async def test_get_transport_redis_exception_falls_back_to_memory(self):
        """Redis.get raises → falls back to in-memory dict (lines 47-49)."""
        reg = TransportRegistry()
        reg._memory["fallback.com"] = "flaresolverr"

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=OSError("redis gone"))
        reg._redis = mock_redis

        result = await reg.get_transport("fallback.com")

        assert result == "flaresolverr"

    @pytest.mark.asyncio
    async def test_set_transport_redis_hit(self):
        """Redis available → r.set() called with correct key (lines 54-56)."""
        reg = TransportRegistry()

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        reg._redis = mock_redis

        await reg.set_transport("example.com", "curl")

        mock_redis.set.assert_awaited_once_with("transport:example.com", "curl")
        # Memory dict should NOT be updated when Redis succeeds
        assert "example.com" not in reg._memory

    @pytest.mark.asyncio
    async def test_set_transport_redis_exception_falls_back_to_memory(self):
        """Redis.set raises → writes to in-memory dict (lines 57-59)."""
        reg = TransportRegistry()

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=OSError("redis gone"))
        reg._redis = mock_redis

        await reg.set_transport("example.com", "flaresolverr")

        assert reg._memory.get("example.com") == "flaresolverr"

    @pytest.mark.asyncio
    async def test_set_transport_no_redis_writes_memory(self):
        """No Redis (None) → writes directly to _memory dict (line 59)."""
        reg = TransportRegistry()
        reg._redis = None
        # Prevent actual Redis connection attempt
        reg._get_redis = AsyncMock(return_value=None)

        await reg.set_transport("example.com", "curl")

        assert reg._memory.get("example.com") == "curl"


class TestTransportRegistryInMemoryFallback:
    """Tests for in-memory block counting (lines 67-71)."""

    @pytest.mark.asyncio
    async def test_record_blocked_in_memory_increments_counter(self):
        """No Redis: _blocks dict incremented (lines 70-71)."""
        reg = TransportRegistry(threshold=5)
        reg._redis = None
        reg._get_redis = AsyncMock(return_value=None)

        await reg.record_blocked("slow.com")
        await reg.record_blocked("slow.com")

        assert reg._blocks["slow.com"] == 2

    @pytest.mark.asyncio
    async def test_record_blocked_in_memory_promotes_at_threshold(self):
        """In-memory block count hits threshold → transport promoted (lines 67-71, 73-82)."""
        reg = TransportRegistry(threshold=3)
        reg._redis = None
        reg._get_redis = AsyncMock(return_value=None)

        for _ in range(3):
            await reg.record_blocked("heavy.com")

        transport = await reg.get_transport("heavy.com")
        assert transport == "curl"

    @pytest.mark.asyncio
    async def test_record_blocked_redis_exception_silently_skips(self):
        """Redis.incr raises → exception is swallowed, count stays 0, no promotion (lines 67-68)."""
        reg = TransportRegistry(threshold=3)

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=OSError("redis gone"))
        # get is called only during promotion check; not reached because count=0
        mock_redis.get = AsyncMock(return_value=b"httpx")
        reg._redis = mock_redis

        await reg.record_blocked("nored.com")

        # count stays 0 — no promotion, no memory update
        assert reg._blocks["nored.com"] == 0
        mock_redis.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_blocked_redis_incr_promotes(self):
        """Redis.incr returns count ≥ threshold → transport promoted via Redis set (lines 66, 73-82)."""
        reg = TransportRegistry(threshold=3)

        mock_redis = AsyncMock()
        # incr returns 3 (threshold reached)
        mock_redis.incr = AsyncMock(return_value=3)
        # get returns current transport
        mock_redis.get = AsyncMock(return_value=b"httpx")
        mock_redis.set = AsyncMock(return_value=True)
        reg._redis = mock_redis

        await reg.record_blocked("blocked.com")

        mock_redis.set.assert_awaited_once_with("transport:blocked.com", "curl")

    @pytest.mark.asyncio
    async def test_record_blocked_already_at_max_tier_no_promotion(self):
        """Domain already at 'flaresolverr' (max tier) → no further promotion."""
        reg = TransportRegistry(threshold=2)
        reg._redis = None
        reg._get_redis = AsyncMock(return_value=None)
        reg._memory["max.com"] = "flaresolverr"
        reg._blocks["max.com"] = 1

        await reg.record_blocked("max.com")

        # Should still be at flaresolverr (can't go higher)
        assert reg._memory.get("max.com") == "flaresolverr"


# ===========================================================================
# shared/health.py
# ===========================================================================


class TestCheckBypassLayers:
    """Tests for shared/health.py functions (lines 20, 30-31, 44-45)."""

    @pytest.mark.asyncio
    async def test_check_flaresolverr_returns_true_on_200(self):
        """_check_flaresolverr: 200 response → True (line 20)."""
        from shared.health import _check_flaresolverr

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.health.httpx.AsyncClient", return_value=mock_client):
            result = await _check_flaresolverr()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_flaresolverr_returns_false_on_non_200(self):
        """_check_flaresolverr: non-200 → False."""
        from shared.health import _check_flaresolverr

        mock_resp = MagicMock()
        mock_resp.status_code = 503

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.health.httpx.AsyncClient", return_value=mock_client):
            result = await _check_flaresolverr()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_flaresolverr_exception_returns_false(self):
        """_check_flaresolverr: exception → False."""
        from shared.health import _check_flaresolverr

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=OSError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.health.httpx.AsyncClient", return_value=mock_client):
            result = await _check_flaresolverr()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_tor_returns_true(self):
        """_check_tor: 200 + IsTor=True → True (lines 30-31)."""
        from shared.health import _check_tor

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"IsTor": True})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.health.httpx.AsyncClient", return_value=mock_client):
            result = await _check_tor(9050)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_tor_returns_false_when_not_tor(self):
        """_check_tor: IsTor=False → False."""
        from shared.health import _check_tor

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"IsTor": False})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.health.httpx.AsyncClient", return_value=mock_client):
            result = await _check_tor(9050)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_tor_exception_returns_false(self):
        """_check_tor: exception → False."""
        from shared.health import _check_tor

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=OSError("socks5 down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.health.httpx.AsyncClient", return_value=mock_client):
            result = await _check_tor(9052)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_dragonfly_returns_true(self):
        """_check_dragonfly: ping succeeds → True (lines 44-45)."""
        from shared.health import _check_dragonfly

        import sys
        import types

        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(return_value=True)
        mock_redis_instance.aclose = AsyncMock()

        fake_aioredis = types.ModuleType("redis.asyncio")
        fake_aioredis.from_url = MagicMock(return_value=mock_redis_instance)

        fake_redis_mod = types.ModuleType("redis")
        fake_redis_mod.asyncio = fake_aioredis
        sys.modules["redis"] = fake_redis_mod
        sys.modules["redis.asyncio"] = fake_aioredis

        try:
            result = await _check_dragonfly()
        finally:
            sys.modules.pop("redis", None)
            sys.modules.pop("redis.asyncio", None)
            try:
                import redis as real_redis
                sys.modules["redis"] = real_redis
                sys.modules["redis.asyncio"] = real_redis.asyncio
            except ImportError:
                pass

        assert result is True

    @pytest.mark.asyncio
    async def test_check_dragonfly_exception_returns_false(self):
        """_check_dragonfly: ping raises → False."""
        from shared.health import _check_dragonfly

        import sys
        import types

        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock(side_effect=OSError("connection refused"))

        fake_aioredis = types.ModuleType("redis.asyncio")
        fake_aioredis.from_url = MagicMock(return_value=mock_redis_instance)

        fake_redis_mod = types.ModuleType("redis")
        fake_redis_mod.asyncio = fake_aioredis
        sys.modules["redis"] = fake_redis_mod
        sys.modules["redis.asyncio"] = fake_aioredis

        try:
            result = await _check_dragonfly()
        finally:
            sys.modules.pop("redis", None)
            sys.modules.pop("redis.asyncio", None)
            try:
                import redis as real_redis
                sys.modules["redis"] = real_redis
                sys.modules["redis.asyncio"] = real_redis.asyncio
            except ImportError:
                pass

        assert result is False

    @pytest.mark.asyncio
    async def test_check_bypass_layers_aggregates_results(self):
        """check_bypass_layers() calls all checks and returns dict with all 6 keys."""
        from shared.health import check_bypass_layers

        with (
            patch("shared.health._check_flaresolverr", new_callable=AsyncMock, return_value=True),
            patch("shared.health._check_tor", new_callable=AsyncMock, return_value=False),
            patch("shared.health._check_dragonfly", new_callable=AsyncMock, return_value=True),
            patch("shared.health._check_postgres", new_callable=AsyncMock, return_value=False),
        ):
            result = await check_bypass_layers()

        assert set(result.keys()) == {"flaresolverr", "tor_1", "tor_2", "tor_3", "dragonfly", "postgres"}
        assert result["flaresolverr"] is True
        assert result["dragonfly"] is True
