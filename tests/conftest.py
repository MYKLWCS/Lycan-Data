import asyncio

import pytest

from shared.db import get_test_db
from shared.events import get_event_bus


@pytest.fixture
async def db():
    async for session in get_test_db():
        yield session


@pytest.fixture(scope="session", autouse=True)
def flush_test_queues():
    """Flush stale items from test queues before any test runs."""

    async def _flush():
        try:
            async with get_event_bus() as bus:
                for queue_key in bus.QUEUES.values():
                    await bus.redis.delete(queue_key)
        except Exception:
            pass  # If Redis is unavailable, tests handle it individually

    asyncio.run(_flush())
