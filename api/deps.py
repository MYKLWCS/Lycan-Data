from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.db import get_db

# ── Database dependency ──────────────────────────────────────────────────────

async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session


DbDep = Depends(db_session)

# ── API key authentication ───────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=True)


def _valid_keys() -> set[str]:
    """Parse API keys from config. Cached per-call (config doesn't change at runtime)."""
    raw = settings.api_keys.strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Validate the Bearer token against configured API keys.

    Returns the validated API key string on success.
    Raises 401 if auth is enabled and the key is invalid.
    """
    if not settings.api_auth_enabled:
        return credentials.credentials

    valid = _valid_keys()
    if not valid:
        # No keys configured — reject everything (fail closed)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API keys not configured. Set LYCAN_API_KEYS in environment.",
        )

    if credentials.credentials not in valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials


ApiKeyDep = Depends(verify_api_key)
