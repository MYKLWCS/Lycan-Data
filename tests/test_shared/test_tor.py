from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.config import settings
from shared.tor import TorEndpoint, TorInstance, TorManager


def test_get_proxy_returns_socks_url():
    """When Tor is enabled (default), returns the correct SOCKS5 URL."""
    mgr = TorManager()
    proxy = mgr.get_proxy(TorInstance.TOR1)
    assert proxy.startswith("socks5://")


def test_get_proxy_disabled_returns_empty():
    mgr = TorManager()
    with patch.object(settings, "tor_enabled", False):
        proxy = mgr.get_proxy(TorInstance.TOR1)
        assert proxy == ""


def test_get_proxy_override():
    mgr = TorManager()
    with patch.object(settings, "proxy_override", "socks5://custom:1080"):
        proxy = mgr.get_proxy(TorInstance.TOR1)
        assert proxy == "socks5://custom:1080"


def test_get_proxy_for_role():
    mgr = TorManager()
    # darkweb role maps to TOR3
    proxy = mgr.get_proxy_for_role("darkweb")
    assert "9054" in proxy  # TOR3 is on port 9054


def test_status_all_disconnected_initially():
    mgr = TorManager()
    status = mgr.status()
    assert status == {"tor1": False, "tor2": False, "tor3": False}


@pytest.mark.asyncio
async def test_new_circuit_when_not_connected_returns_false():
    mgr = TorManager()
    result = await mgr.new_circuit(TorInstance.TOR1)
    assert result is False


@pytest.mark.asyncio
async def test_connect_all_when_tor_disabled():
    """When tor_enabled=False, connect_all() returns immediately without error."""
    mgr = TorManager()
    with patch.object(settings, "tor_enabled", False):
        await mgr.connect_all()  # should not raise
    assert mgr.status() == {"tor1": False, "tor2": False, "tor3": False}


@pytest.mark.asyncio
async def test_connect_all_handles_connection_failure_gracefully():
    """If Tor ports are not reachable, connect_all() logs warnings but doesn't raise."""
    mgr = TorManager()
    # Tor is not started in test env — should fail gracefully
    await mgr.connect_all()
    # All should remain disconnected, but no exception
    assert all(not ep.is_connected for ep in mgr._endpoints.values())
