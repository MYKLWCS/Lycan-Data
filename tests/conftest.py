import pytest

from shared.db import get_test_db


@pytest.fixture
async def db():
    async for session in get_test_db():
        yield session
