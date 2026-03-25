import pytest

from shared.transport_registry import TransportRegistry


@pytest.mark.asyncio
async def test_default_transport_is_httpx():
    reg = TransportRegistry()
    t = await reg.get_transport("example.com")
    assert t == "httpx"


@pytest.mark.asyncio
async def test_record_blocked_promotes_after_threshold():
    reg = TransportRegistry(threshold=3)
    for _ in range(3):
        await reg.record_blocked("example.com")
    t = await reg.get_transport("example.com")
    assert t == "curl"
