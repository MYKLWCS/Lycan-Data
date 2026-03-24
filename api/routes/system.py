"""System health, stats, and operational endpoints."""
import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep, db_session
from modules.crawlers.registry import list_platforms, CRAWLER_REGISTRY
from shared.tor import tor_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health():
    """
    Full system health check.

    Probes Redis, PostgreSQL, Tor, and the rate-limiter/circuit-breaker stack.
    Returns overall status "ok" only when all critical services are healthy.
    """
    results: dict = {}
    t0 = time.monotonic()

    # ── Redis / Dragonfly ──────────────────────────────────────────────────────
    from shared.events import event_bus
    redis_ok = False
    redis_latency_ms = None
    try:
        t = time.monotonic()
        await event_bus.redis.ping()
        redis_latency_ms = round((time.monotonic() - t) * 1000, 2)
        redis_ok = True
    except Exception as exc:
        results["redis_error"] = str(exc)

    results["redis"] = {"ok": redis_ok, "latency_ms": redis_latency_ms}

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    db_ok = False
    db_latency_ms = None
    try:
        from shared.db import AsyncSessionLocal
        from sqlalchemy import text as sa_text
        t = time.monotonic()
        async with AsyncSessionLocal() as session:
            await session.execute(sa_text("SELECT 1"))
        db_latency_ms = round((time.monotonic() - t) * 1000, 2)
        db_ok = True
    except Exception as exc:
        results["db_error"] = str(exc)

    results["db"] = {"ok": db_ok, "latency_ms": db_latency_ms}

    # ── Tor ────────────────────────────────────────────────────────────────────
    tor_status = tor_manager.status()
    results["tor"] = tor_status

    # ── Rate limiter / circuit breaker ─────────────────────────────────────────
    try:
        from shared.rate_limiter import get_rate_limiter
        rl_tokens = await get_rate_limiter().peek("__health_probe__")
        results["rate_limiter"] = {"ok": True, "probe_tokens": round(rl_tokens, 2)}
    except Exception as exc:
        results["rate_limiter"] = {"ok": False, "error": str(exc)}

    # ── Crawler registry ───────────────────────────────────────────────────────
    results["crawlers"] = {
        "registered": len(CRAWLER_REGISTRY),
    }
    results["crawlers_registered"] = len(CRAWLER_REGISTRY)  # flat field for UI

    # ── Overall ────────────────────────────────────────────────────────────────
    critical_ok = redis_ok and db_ok
    total_ms = round((time.monotonic() - t0) * 1000, 2)

    return {
        "status": "ok" if critical_ok else "degraded",
        "total_check_ms": total_ms,
        **results,
    }


@router.get("/health/simple")
async def health_simple():
    """Lightweight liveness probe — no DB/Redis checks. Always returns 200."""
    return {"status": "ok", "crawlers_registered": len(CRAWLER_REGISTRY)}


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
async def queue_stats(session: AsyncSession = DbDep):
    """Return queue depths + cumulative throughput stats for the pipeline banner."""
    from shared.events import event_bus
    from sqlalchemy import text

    try:
        queues = {}
        for name in ("high", "normal", "low", "ingest", "index"):
            queues[name] = await event_bus.queue_length(name)
        total_pending = queues["high"] + queues["normal"] + queues["low"]

        # Cumulative throughput from DB (shown as "X ingested / Y indexed")
        row = (await session.execute(text(
            "SELECT COUNT(*) as total_logs, "
            "SUM(CASE WHEN meta->>'success'='true' THEN 1 ELSE 0 END) as found_count "
            "FROM crawl_logs"
        ))).mappings().one()
        persons_row = (await session.execute(text(
            "SELECT COUNT(*) as total FROM persons"
        ))).mappings().one()

        return {
            "queues": queues,
            "total_pending": total_pending,
            "ingest_backlog": queues["ingest"],
            "index_backlog": queues["index"],
            # Throughput counters for banner
            "crawls_total": int(row["total_logs"] or 0),
            "crawls_found": int(row["found_count"] or 0),
            "persons_total": int(persons_row["total"] or 0),
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


@router.get("/circuit-breakers")
async def circuit_breaker_status():
    """Return circuit breaker states for all tracked domains."""
    from shared.events import event_bus

    if not event_bus.is_connected:
        return {"error": "Redis not connected", "breakers": {}}

    try:
        keys = await event_bus.redis.keys("lycan:cb:*")
        breakers: dict = {}
        for raw_key in keys:
            redis_key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            domain = redis_key.removeprefix("lycan:cb:")
            from shared.circuit_breaker import get_circuit_breaker
            breakers[domain] = await get_circuit_breaker().get_state(domain)
        return {"breakers": breakers, "count": len(breakers)}
    except Exception as exc:
        logger.exception("circuit-breakers endpoint failed")
        return {"error": str(exc), "breakers": {}}


@router.post("/circuit-breakers/{domain}/reset")
async def reset_circuit_breaker(domain: str):
    """Manually force a circuit breaker to CLOSED state."""
    from shared.circuit_breaker import get_circuit_breaker
    await get_circuit_breaker().force_close(domain)
    return {"message": f"Circuit breaker for {domain!r} forced to CLOSED", "domain": domain}


@router.get("/rate-limits")
async def rate_limit_status():
    """Return current token counts for all active rate-limit buckets."""
    from shared.events import event_bus

    if not event_bus.is_connected:
        return {"error": "Redis not connected", "buckets": {}}

    try:
        keys = await event_bus.redis.keys("lycan:rl:*")
        buckets: dict = {}
        for raw_key in keys:
            redis_key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            domain = redis_key.removeprefix("lycan:rl:")
            from shared.rate_limiter import get_rate_limiter
            tokens = await get_rate_limiter().peek(domain)
            buckets[domain] = {"tokens": round(tokens, 3)}
        return {"buckets": buckets, "count": len(buckets)}
    except Exception as exc:
        logger.exception("rate-limits endpoint failed")
        return {"error": str(exc), "buckets": {}}
