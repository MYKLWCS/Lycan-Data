import uuid

import pytest

from shared.transport_registry import TransportRegistry


@pytest.mark.asyncio
async def test_default_transport_is_httpx():
    reg = TransportRegistry()
    domain = f"test-default-{uuid.uuid4()}.invalid"
    t = await reg.get_transport(domain)
    assert t == "httpx"


@pytest.mark.asyncio
async def test_record_blocked_promotes_after_threshold():
    domain = f"test-blocked-{uuid.uuid4()}.invalid"
    reg = TransportRegistry(threshold=3)
    for _ in range(3):
        await reg.record_blocked(domain)
    t = await reg.get_transport(domain)
    assert t == "curl"
