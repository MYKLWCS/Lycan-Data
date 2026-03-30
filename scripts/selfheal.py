"""Self-heal: check and repair common environment issues."""

import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("selfheal")


async def check_database():
    try:
        from shared.config import settings
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        engine = create_async_engine(settings.database_url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        log.info("Database: OK")
        return True
    except Exception as e:
        log.error("Database: FAILED - %s", e)
        return False


async def check_cache():
    try:
        from shared.config import settings
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.cache_url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        log.info("Cache: OK")
        return True
    except Exception as e:
        log.error("Cache: FAILED - %s", e)
        return False


async def check_typesense():
    try:
        from shared.config import settings
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.typesense_url}/health")
            if r.status_code == 200:
                log.info("Typesense: OK")
                return True
            log.error("Typesense: HTTP %d", r.status_code)
            return False
    except Exception as e:
        log.error("Typesense: FAILED - %s", e)
        return False


async def check_crawlers():
    try:
        from api.main import _import_all_crawlers
        _import_all_crawlers()
        from modules.crawlers.registry import CRAWLER_REGISTRY
        count = len(CRAWLER_REGISTRY)
        log.info("Crawlers: %d registered", count)
        return count > 150
    except Exception as e:
        log.error("Crawlers: FAILED - %s", e)
        return False


async def main():
    results = await asyncio.gather(
        check_database(),
        check_cache(),
        check_typesense(),
        check_crawlers(),
    )
    ok = all(results)
    log.info("Overall: %s", "HEALTHY" if ok else "DEGRADED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
