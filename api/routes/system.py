from fastapi import APIRouter

from modules.crawlers.registry import list_platforms, CRAWLER_REGISTRY
from shared.tor import tor_manager

router = APIRouter()


@router.get("/health")
async def health():
    from shared.events import event_bus

    try:
        await event_bus.redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status": "ok",
        "redis": redis_ok,
        "tor": tor_manager.status(),
        "crawlers_registered": len(CRAWLER_REGISTRY),
    }


@router.get("/stats")
async def stats():
    return {
        "crawlers": len(CRAWLER_REGISTRY),
        "platforms": sorted(list_platforms()),
    }


@router.get("/registry")
async def registry():
    return {
        "platforms": sorted(list_platforms()),
        "count": len(CRAWLER_REGISTRY),
    }
