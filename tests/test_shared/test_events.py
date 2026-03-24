import pytest

from shared.events import EventBus, get_event_bus


@pytest.mark.asyncio
async def test_event_bus_connects():
    bus = EventBus()
    await bus.connect()
    assert bus._redis is not None
    await bus.disconnect()


@pytest.mark.asyncio
async def test_publish_and_queue():
    async with get_event_bus() as bus:
        # Test queue
        await bus.enqueue({"job_type": "test", "value": 42}, priority="high")
        length = await bus.queue_length("high")
        assert length >= 1
        job = await bus.dequeue("high", timeout=2)
        assert job is not None
        assert job["job_type"] == "test"
        assert job["value"] == 42


@pytest.mark.asyncio
async def test_cache_set_get_delete():
    async with get_event_bus() as bus:
        await bus.cache_set("test:key", {"hello": "world"}, ttl_seconds=10)
        val = await bus.cache_get("test:key")
        assert val == {"hello": "world"}
        await bus.cache_delete("test:key")
        val2 = await bus.cache_get("test:key")
        assert val2 is None


@pytest.mark.asyncio
async def test_dequeue_empty_returns_none():
    async with get_event_bus() as bus:
        # Use a unique queue key to avoid interference
        result = await bus.redis.brpop(["lycan:queue:empty_test_xyz"], timeout=1)
        assert result is None
