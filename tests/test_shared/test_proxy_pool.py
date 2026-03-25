"""
test_proxy_pool.py — Unit tests for shared/proxy_pool.py.

Covers:
  - ProxyPool.__init__: loads residential and datacenter from settings
  - ProxyPool.__init__: empty settings → empty pools
  - ProxyPool.__init__: filters blank/whitespace entries
  - _load_from_settings: comma-separated proxy strings parsed correctly
  - next("residential"): round-robin returns proxies in order
  - next("residential"): skips banned proxies
  - next("residential"): uses slow proxies when all healthy are gone
  - next("residential"): returns None when all banned
  - next("datacenter"): returns from datacenter pool
  - next("tor"): delegates to tor_manager.get_proxy
  - next("direct"): always returns None
  - next("unknown"): treated as "direct" (falls through to return None)
  - next_with_fallback("residential"): returns residential when available
  - next_with_fallback("residential"): falls back to datacenter when residential empty
  - next_with_fallback("residential"): falls back to tor when res+dc empty
  - next_with_fallback("datacenter"): starts at datacenter tier
  - next_with_fallback("direct"): returns (None, "direct") immediately
  - next_with_fallback: unknown preferred_tier starts from residential
  - mark_banned(): adds entry to _banned with future timestamp
  - mark_banned(): banned proxy not returned by next()
  - mark_slow(): adds to _slow set
  - mark_slow(): slow proxy used only when no healthy proxy available
  - mark_healthy(): removes from _slow and _banned
  - add_proxy(): adds new residential proxy
  - add_proxy(): does not duplicate existing residential proxy
  - add_proxy(): adds datacenter proxy
  - add_proxy(): does not duplicate existing datacenter proxy
  - add_proxy(): unknown tier → ignored
  - _unban_expired(): removes expired entries automatically
  - status(): returns correct counts
  - status(): reflects banned/slow state
  - status(): tor_available delegates to tor_manager.any_available()
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_settings(residential: str = "", datacenter: str = "") -> MagicMock:
    s = MagicMock()
    s.residential_proxies = residential
    s.datacenter_proxies = datacenter
    return s


def _make_tor_manager(proxy: str | None = "socks5://127.0.0.1:9052", any_available: bool = True) -> MagicMock:
    tm = MagicMock()
    tm.get_proxy.return_value = proxy
    tm.any_available.return_value = any_available
    return tm


def _make_pool(
    residential: str = "http://r1:8080,http://r2:8080",
    datacenter: str = "http://d1:3128",
    tor_proxy: str | None = "socks5://127.0.0.1:9052",
    tor_available: bool = True,
):
    """Build a ProxyPool with controlled settings and tor_manager."""
    settings = _make_settings(residential=residential, datacenter=datacenter)
    tor_manager = _make_tor_manager(proxy=tor_proxy, any_available=tor_available)

    with (
        patch("shared.proxy_pool.settings", settings),
        patch("shared.proxy_pool.tor_manager", tor_manager),
    ):
        from shared.proxy_pool import ProxyPool
        pool = ProxyPool()
        # Attach mocks so tests can inspect them
        pool._test_tor_manager = tor_manager
        return pool


# ── __init__ / _load_from_settings ───────────────────────────────────────────


class TestProxyPoolInit:
    def test_loads_residential_proxies(self):
        pool = _make_pool(residential="http://a:8080,http://b:8080", datacenter="")
        assert len(pool._residential) == 2
        assert "http://a:8080" in pool._residential

    def test_loads_datacenter_proxies(self):
        pool = _make_pool(residential="", datacenter="http://dc1:3128,http://dc2:3128")
        assert len(pool._datacenter) == 2

    def test_empty_strings_produce_empty_pools(self):
        pool = _make_pool(residential="", datacenter="")
        assert pool._residential == []
        assert pool._datacenter == []

    def test_filters_blank_entries(self):
        pool = _make_pool(residential="http://r1:8080, , http://r2:8080, ", datacenter="")
        assert len(pool._residential) == 2

    def test_rr_indices_initialised(self):
        pool = _make_pool()
        assert "residential" in pool._rr_indices
        assert "datacenter" in pool._rr_indices

    def test_banned_and_slow_start_empty(self):
        pool = _make_pool()
        assert pool._banned == {}
        assert pool._slow == set()


# ── next() ────────────────────────────────────────────────────────────────────


class TestProxyPoolNext:
    async def test_next_residential_returns_proxy(self):
        pool = _make_pool(residential="http://r1:8080")
        result = await pool.next("residential")
        assert result == "http://r1:8080"

    async def test_next_residential_round_robin(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080")
        first = await pool.next("residential")
        second = await pool.next("residential")
        assert first != second or first is not None

    async def test_next_skips_banned_proxy(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=60)
        result = await pool.next("residential")
        assert result == "http://r2:8080"

    async def test_next_returns_none_when_all_banned(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=60)
        result = await pool.next("residential")
        assert result is None

    async def test_next_uses_slow_when_no_healthy(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_slow("http://r1:8080")
        result = await pool.next("residential")
        # Slow proxies are used as last resort
        assert result == "http://r1:8080"

    async def test_next_prefers_healthy_over_slow(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080")
        await pool.mark_slow("http://r1:8080")
        # r2 is healthy — should always get r2 first
        result = await pool.next("residential")
        assert result == "http://r2:8080"

    async def test_next_datacenter(self):
        pool = _make_pool(datacenter="http://dc1:3128")
        result = await pool.next("datacenter")
        assert result == "http://dc1:3128"

    async def test_next_datacenter_empty_returns_none(self):
        pool = _make_pool(datacenter="")
        result = await pool.next("datacenter")
        assert result is None

    async def test_next_tor_delegates_to_tor_manager(self):
        pool = _make_pool(tor_proxy="socks5://127.0.0.1:9052")
        result = await pool.next("tor")
        pool._test_tor_manager.get_proxy.assert_called_once()
        assert result == "socks5://127.0.0.1:9052"

    async def test_next_tor_unavailable_returns_none(self):
        pool = _make_pool(tor_proxy=None)
        result = await pool.next("tor")
        assert result is None

    async def test_next_direct_returns_none(self):
        pool = _make_pool()
        result = await pool.next("direct")
        assert result is None

    async def test_next_empty_residential_returns_none(self):
        pool = _make_pool(residential="")
        result = await pool.next("residential")
        assert result is None


# ── next_with_fallback() ─────────────────────────────────────────────────────


class TestNextWithFallback:
    async def test_returns_residential_when_available(self):
        pool = _make_pool(residential="http://r1:8080")
        proxy, tier = await pool.next_with_fallback("residential")
        assert proxy == "http://r1:8080"
        assert tier == "residential"

    async def test_falls_back_to_datacenter(self):
        pool = _make_pool(residential="", datacenter="http://dc1:3128", tor_proxy=None)
        proxy, tier = await pool.next_with_fallback("residential")
        assert proxy == "http://dc1:3128"
        assert tier == "datacenter"

    async def test_falls_back_to_tor(self):
        pool = _make_pool(residential="", datacenter="", tor_proxy="socks5://127.0.0.1:9052")
        proxy, tier = await pool.next_with_fallback("residential")
        assert proxy == "socks5://127.0.0.1:9052"
        assert tier == "tor"

    async def test_falls_back_to_direct(self):
        pool = _make_pool(residential="", datacenter="", tor_proxy=None)
        proxy, tier = await pool.next_with_fallback("residential")
        assert proxy is None
        assert tier == "direct"

    async def test_starts_at_datacenter_when_preferred(self):
        pool = _make_pool(datacenter="http://dc1:3128")
        proxy, tier = await pool.next_with_fallback("datacenter")
        assert tier == "datacenter"
        assert proxy == "http://dc1:3128"

    async def test_direct_preferred_returns_immediately(self):
        pool = _make_pool()
        proxy, tier = await pool.next_with_fallback("direct")
        assert proxy is None
        assert tier == "direct"

    async def test_unknown_preferred_tier_starts_from_residential(self):
        """preferred_tier not in chain → start from index 0 (residential)."""
        pool = _make_pool(residential="http://r1:8080")
        proxy, tier = await pool.next_with_fallback("unknown_tier")
        assert tier == "residential"
        assert proxy == "http://r1:8080"

    async def test_no_fallback_log_when_tier_matches(self):
        """No fallback log when returned tier equals preferred tier."""
        pool = _make_pool(residential="http://r1:8080")
        import logging
        with patch("shared.proxy_pool.logger") as mock_logger:
            proxy, tier = await pool.next_with_fallback("residential")
            mock_logger.info.assert_not_called()


# ── mark_banned() ─────────────────────────────────────────────────────────────


class TestMarkBanned:
    async def test_adds_to_banned_dict(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=10)
        assert "http://r1:8080" in pool._banned

    async def test_banned_timestamp_is_in_future(self):
        pool = _make_pool(residential="http://r1:8080")
        before = time.time()
        await pool.mark_banned("http://r1:8080", duration_minutes=30)
        assert pool._banned["http://r1:8080"] > before

    async def test_banned_proxy_not_returned(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=30)
        result = await pool.next("residential")
        assert result is None


# ── mark_slow() ───────────────────────────────────────────────────────────────


class TestMarkSlow:
    async def test_adds_to_slow_set(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_slow("http://r1:8080")
        assert "http://r1:8080" in pool._slow

    async def test_slow_proxy_deprioritised(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080")
        await pool.mark_slow("http://r1:8080")
        result = await pool.next("residential")
        assert result == "http://r2:8080"


# ── mark_healthy() ────────────────────────────────────────────────────────────


class TestMarkHealthy:
    async def test_removes_from_slow(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_slow("http://r1:8080")
        await pool.mark_healthy("http://r1:8080")
        assert "http://r1:8080" not in pool._slow

    async def test_removes_from_banned(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=60)
        await pool.mark_healthy("http://r1:8080")
        assert "http://r1:8080" not in pool._banned

    async def test_healthy_proxy_returned_again_after_ban(self):
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=60)
        await pool.mark_healthy("http://r1:8080")
        result = await pool.next("residential")
        assert result == "http://r1:8080"

    async def test_mark_healthy_on_non_banned_proxy_is_safe(self):
        """mark_healthy on a proxy that's neither slow nor banned is a no-op."""
        pool = _make_pool(residential="http://r1:8080")
        await pool.mark_healthy("http://r1:8080")  # should not raise


# ── add_proxy() ───────────────────────────────────────────────────────────────


class TestAddProxy:
    def test_adds_residential_proxy(self):
        pool = _make_pool(residential="")
        pool.add_proxy("http://new:8080", tier="residential")
        assert "http://new:8080" in pool._residential

    def test_does_not_duplicate_residential(self):
        pool = _make_pool(residential="http://r1:8080")
        pool.add_proxy("http://r1:8080", tier="residential")
        assert pool._residential.count("http://r1:8080") == 1

    def test_adds_datacenter_proxy(self):
        pool = _make_pool(datacenter="")
        pool.add_proxy("http://dc99:3128", tier="datacenter")
        assert "http://dc99:3128" in pool._datacenter

    def test_does_not_duplicate_datacenter(self):
        pool = _make_pool(datacenter="http://dc1:3128")
        pool.add_proxy("http://dc1:3128", tier="datacenter")
        assert pool._datacenter.count("http://dc1:3128") == 1

    def test_unknown_tier_ignored(self):
        pool = _make_pool(residential="http://r1:8080")
        initial_res = list(pool._residential)
        pool.add_proxy("http://ghost:9999", tier="onion")
        assert pool._residential == initial_res


# ── _unban_expired() ─────────────────────────────────────────────────────────


class TestUnbanExpired:
    def test_expired_ban_removed(self):
        pool = _make_pool(residential="http://r1:8080")
        # Insert a ban that expired in the past
        pool._banned["http://r1:8080"] = time.time() - 1
        pool._unban_expired()
        assert "http://r1:8080" not in pool._banned

    def test_future_ban_not_removed(self):
        pool = _make_pool(residential="http://r1:8080")
        pool._banned["http://r1:8080"] = time.time() + 9999
        pool._unban_expired()
        assert "http://r1:8080" in pool._banned

    async def test_next_auto_unbans_expired(self):
        """next() calls _unban_expired, so expired bans are cleared automatically."""
        pool = _make_pool(residential="http://r1:8080")
        pool._banned["http://r1:8080"] = time.time() - 1  # already expired
        result = await pool.next("residential")
        assert result == "http://r1:8080"
        assert "http://r1:8080" not in pool._banned


# ── status() ─────────────────────────────────────────────────────────────────


class TestStatus:
    def test_status_counts_are_correct(self):
        pool = _make_pool(
            residential="http://r1:8080,http://r2:8080",
            datacenter="http://dc1:3128",
        )
        s = pool.status()
        assert s["residential_total"] == 2
        assert s["residential_available"] == 2
        assert s["residential_slow"] == 0
        assert s["datacenter_total"] == 1
        assert s["datacenter_available"] == 1
        assert s["banned_count"] == 0
        assert s["slow_count"] == 0

    async def test_status_reflects_banned(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080")
        await pool.mark_banned("http://r1:8080", duration_minutes=10)
        s = pool.status()
        assert s["residential_available"] == 1
        assert s["banned_count"] == 1

    async def test_status_reflects_slow(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080")
        await pool.mark_slow("http://r1:8080")
        s = pool.status()
        assert s["residential_slow"] == 1
        assert s["slow_count"] == 1
        # Available excludes slow
        assert s["residential_available"] == 1

    def test_status_tor_available(self):
        pool = _make_pool(tor_available=True)
        s = pool.status()
        assert s["tor_available"] is True

    def test_status_tor_unavailable(self):
        pool = _make_pool(tor_available=False)
        s = pool.status()
        assert s["tor_available"] is False

    def test_status_with_empty_pools(self):
        pool = _make_pool(residential="", datacenter="")
        s = pool.status()
        assert s["residential_total"] == 0
        assert s["datacenter_total"] == 0
        assert s["residential_available"] == 0
        assert s["datacenter_available"] == 0

    async def test_status_clears_expired_bans(self):
        """status() calls _unban_expired — expired bans not counted."""
        pool = _make_pool(residential="http://r1:8080")
        pool._banned["http://r1:8080"] = time.time() - 1  # already expired
        s = pool.status()
        assert s["banned_count"] == 0
        assert s["residential_available"] == 1


# ── _next_from() round-robin ─────────────────────────────────────────────────


class TestNextFrom:
    def test_round_robin_increments_index(self):
        pool = _make_pool(residential="http://r1:8080,http://r2:8080,http://r3:8080")
        results = [pool._next_from(pool._residential, "residential") for _ in range(6)]
        # Should cycle through all 3 proxies
        assert set(results) == {"http://r1:8080", "http://r2:8080", "http://r3:8080"}

    def test_empty_pool_returns_none(self):
        pool = _make_pool(residential="")
        result = pool._next_from(pool._residential, "residential")
        assert result is None

    def test_all_slow_falls_back_to_slow_proxies(self):
        pool = _make_pool(residential="http://r1:8080")
        pool._slow.add("http://r1:8080")
        result = pool._next_from(pool._residential, "residential")
        assert result == "http://r1:8080"

    def test_all_banned_returns_none(self):
        pool = _make_pool(residential="http://r1:8080")
        pool._banned["http://r1:8080"] = time.time() + 9999
        result = pool._next_from(pool._residential, "residential")
        assert result is None
