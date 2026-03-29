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

# auto_error=False so we can raise 401 (not 403) for missing Authorization header
_bearer = HTTPBearer(auto_error=False)


def _valid_keys() -> set[str]:
    """Parse API keys from config. Cached per-call (config doesn't change at runtime)."""
    raw = settings.api_keys.strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Validate the Bearer token against configured API keys.

    Returns the validated API key string on success.
    Raises 401 for missing or invalid credentials (HTTP spec: 401 = not authenticated).
    """
    # Auth disabled — allow all requests (dev/local mode)
    if not settings.api_auth_enabled:
        return (credentials.credentials if credentials else "anonymous")

    # Missing Authorization header → 401 Unauthorized
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    valid = _valid_keys()
    if not valid:
        # No keys configured — reject everything (fail closed)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API keys not configured. Set LYCAN_API_KEYS in environment.",
        )

    # Invalid/wrong key → 401 Unauthorized
    if credentials.credentials not in valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


ApiKeyDep = Depends(verify_api_key)
