import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_test_db


@pytest.mark.asyncio
async def test_db_connects():
    """Verify we can connect and run a query."""
    async for session in get_test_db():
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_db_session_is_async_session():
    async for session in get_test_db():
        assert isinstance(session, AsyncSession)


@pytest.mark.asyncio
async def test_db_pgvector_extension():
    """Verify pgvector extension is installed."""
    async for session in get_test_db():
        result = await session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        assert result.scalar() == "vector"


@pytest.mark.asyncio
async def test_db_uuid_extension():
    """Verify uuid-ossp extension is installed."""
    async for session in get_test_db():
        result = await session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'uuid-ossp'")
        )
        assert result.scalar() == "uuid-ossp"
