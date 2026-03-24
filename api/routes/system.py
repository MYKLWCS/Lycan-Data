"""System health, stats, and operational endpoints."""
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


@router.get("/queues")
async def queue_stats():
    """Return current queue depths for all Dragonfly queues."""
    from shared.events import event_bus

    try:
        queues = {}
        for name in ("high", "normal", "low", "ingest", "index"):
            queues[name] = await event_bus.queue_length(name)
        total_pending = queues["high"] + queues["normal"] + queues["low"]
        return {
            "queues": queues,
            "total_pending": total_pending,
            "ingest_backlog": queues["ingest"],
            "index_backlog": queues["index"],
        }
    except Exception as exc:
        return {"error": str(exc), "queues": {}}


@router.post("/queues/drain")
async def drain_queues(queue: str = "all"):
    """Clear one or all queues (use with caution)."""
    from shared.events import event_bus

    try:
        if queue == "all":
            cleared = {}
            for name, key in event_bus.QUEUES.items():
                length = await event_bus.redis.llen(key)
                if length > 0:
                    await event_bus.redis.delete(key)
                cleared[name] = length
            return {"message": "All queues drained", "cleared": cleared}
        elif queue in event_bus.QUEUES:
            key = event_bus.QUEUES[queue]
            length = await event_bus.redis.llen(key)
            await event_bus.redis.delete(key)
            return {"message": f"Queue '{queue}' drained", "cleared": length}
        else:
            return {"error": f"Unknown queue: {queue}"}
    except Exception as exc:
        return {"error": str(exc)}
