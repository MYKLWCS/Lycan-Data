"""
Startup health check for all bypass layers.
Call check_bypass_layers() at application startup to log availability.
Individual crawlers handle their own unavailability — this is informational only.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


async def _check_flaresolverr() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://localhost:8191/health")
            return r.status_code == 200
    except Exception:
        return False


async def _check_tor(port: int) -> bool:
    try:
        async with httpx.AsyncClient(
            proxies={"all://": f"socks5://127.0.0.1:{port}"}, timeout=10
        ) as c:
            r = await c.get("https://check.torproject.org/api/ip")
            return r.status_code == 200 and r.json().get("IsTor") is True
    except Exception:
        return False


async def _check_dragonfly() -> bool:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url("redis://localhost:6379", socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def _check_postgres() -> bool:
    try:
        import sqlalchemy

        from shared.db import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            await s.execute(sqlalchemy.text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_bypass_layers() -> dict[str, bool]:
    results = await asyncio.gather(
        _check_flaresolverr(),
        _check_tor(9050),
        _check_tor(9052),
        _check_tor(9054),
        _check_dragonfly(),
        _check_postgres(),
        return_exceptions=False,
    )
    status = {
        "flaresolverr": results[0],
        "tor_1": results[1],
        "tor_2": results[2],
        "tor_3": results[3],
        "dragonfly": results[4],
        "postgres": results[5],
    }
    for layer, ok in status.items():
        level = logging.INFO if ok else logging.WARNING
        logger.log(level, "Bypass layer %s: %s", layer, "OK" if ok else "UNAVAILABLE")
    return status
