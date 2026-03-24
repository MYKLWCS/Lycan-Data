from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_db


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session


DbDep = Depends(db_session)
