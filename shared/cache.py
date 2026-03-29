"""Simple Redis/Garnet result cache."""
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from shared.config import settings

logger = logging.getLogger(__name__)
_pool = None


async def get_cache():
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(settings.cache_url, decode_responses=True)
    return _pool


async def cache_get(key: str) -> Any | None:
    try:
        r = await get_cache()
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = 3600) -> None:
    try:
        r = await get_cache()
        await r.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception:
        pass
