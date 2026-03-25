import asyncio
import logging

import pytest

from api.deps import verify_api_key
from api.main import app
from shared.db import get_test_db
from shared.events import get_event_bus

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def disable_api_auth():
    """Bypass API key auth in all tests by default.

    Tests that specifically verify auth behavior (test_auth.py)
    remove this override in their own fixture.
    """

    async def _no_auth():
        return "test-key"

    app.dependency_overrides[verify_api_key] = _no_auth
    yield
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
async def db():
    async for session in get_test_db():
        yield session


@pytest.fixture(scope="session", autouse=True)
def flush_test_queues():
    """Flush stale items from test queues before any test runs.

    Uses an isolated event loop so it doesn't conflict with the loop
    pytest-asyncio manages for individual async tests (asyncio_mode=auto).
    """

    async def _flush():
        try:
            async with get_event_bus() as bus:
                for queue_key in bus.QUEUES.values():
                    await bus.redis.delete(queue_key)
        except Exception:
            pass  # If Redis is unavailable, tests handle it individually

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_flush())
    finally:
        loop.close()


@pytest.fixture(scope="session", autouse=True)
def check_db_reachable():
    """Verify the test DB is reachable at session start.

    Logs a warning if not — individual tests are responsible for skipping
    or handling DB-unavailable conditions themselves.
    """

    async def _check():
        try:
            async for session in get_test_db():
                await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        except Exception as exc:
            logger.warning("Test database is not reachable: %s — DB-dependent tests may fail", exc)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_check())
    finally:
        loop.close()
