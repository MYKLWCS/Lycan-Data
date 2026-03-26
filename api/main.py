import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

_log = logging.getLogger(__name__)

from fastapi import Depends

from api.deps import verify_api_key
from api.routes import (
    alerts,
    audit,
    behavioural,
    builder,
    compliance,
    crawls,
    dedup,
    discovery,
    enrichment,
    export,
    financial,
    graph,
    knowledge_graph,
    marketing,
    patterns,
    persons,
    relationships,
    search,
    search_query,
    system,
    watchlist,
    ws,
)
from shared.events import event_bus

# Auth dependency applied to all protected routers
_auth = [Depends(verify_api_key)]


def _import_all_crawlers() -> None:
    """Auto-import every module under modules.crawlers so they self-register."""
    import modules.crawlers as pkg

    for _, name, _ in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"modules.crawlers.{name}")
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _import_all_crawlers()
    try:
        await event_bus.connect()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("EventBus could not connect — continuing without Redis")
    try:
        from shared.tor import tor_manager

        await tor_manager.connect_all()
    except Exception:
        pass
    try:
        from modules.search.meili_indexer import meili_indexer

        await meili_indexer.setup_index()
        _log.info("Typesense collections initialized")
    except Exception:
        _log.warning("Typesense setup skipped (not available)")
        pass
    # Initialize rate limiter and circuit breaker with shared Redis client
    try:
        from shared.circuit_breaker import init_circuit_breaker
        from shared.rate_limiter import init_rate_limiter

        redis = event_bus.redis if event_bus.is_connected else None
        init_rate_limiter(redis)
        init_circuit_breaker(redis)
    except Exception:
        _log.warning("Rate limiter / circuit breaker init skipped (no Redis)")

    yield

    # ── Graceful shutdown ──────────────────────────────────────────────────────
    try:
        await event_bus.disconnect()
    except Exception:
        pass


app = FastAPI(
    title="Lycan OSINT",
    description="Recursive people intelligence platform",
    version="0.1.0",
    lifespan=lifespan,
)

from shared.config import settings as _settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiting ─────────────────────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    storage_uri=_settings.dragonfly_url,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Audit Logging Middleware ──────────────────────────────────────────────────
import time as _time

from starlette.middleware.base import BaseHTTPMiddleware


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log every authenticated API call (skip health checks)."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/system/health", "/health"):
            return await call_next(request)
        start = _time.monotonic()
        response = await call_next(request)
        duration_ms = round((_time.monotonic() - start) * 1000, 2)
        api_key = request.headers.get("authorization", "")[:20]
        _log.info(
            "AUDIT %s %s %s key=%s ip=%s dur=%.1fms",
            request.method,
            request.url.path,
            response.status_code,
            api_key,
            request.client.host if request.client else "unknown",
            duration_ms,
        )
        # Persist to DB asynchronously (fire-and-forget)
        try:
            from shared.db import AsyncSessionLocal
            from shared.models.audit import AuditRequestLog

            async with AsyncSessionLocal() as session:
                log_entry = AuditRequestLog(
                    api_key=api_key,
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    ip=request.client.host if request.client else "unknown",
                    duration_ms=duration_ms,
                )
                session.add(log_entry)
                await session.commit()
        except Exception:
            pass  # audit logging must never block requests
        return response


app.add_middleware(AuditLogMiddleware)

# ── Static & SPA ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

from fastapi.responses import FileResponse


@app.get("/", include_in_schema=False)
async def ui_index():
    return FileResponse("static/index.html")


@app.get("/ui/graph", include_in_schema=False)
async def ui_knowledge_graph():
    """Serve the Knowledge Graph explorer page."""
    return FileResponse("templates/knowledge_graph.html")


@app.get("/ui/discovery", include_in_schema=False)
async def ui_discovery():
    """Serve the Open Discovery / Review Tab page."""
    return FileResponse("templates/discovery.html")


@app.get("/ui/relationships", include_in_schema=False)
async def ui_relationships():
    """Serve the Interactive Relationship Graph page."""
    return FileResponse("templates/relationship_graph.html")


@app.get("/ui/{path:path}", include_in_schema=False)
async def ui_redirect(path: str):
    """Redirect old /ui/* routes to the SPA hash router."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/#/{path}")


# ── API Routes ────────────────────────────────────────────────────────────────

app.include_router(audit.router, prefix="/audit", tags=["audit"], dependencies=_auth)
app.include_router(search.router, prefix="/search", tags=["search"], dependencies=_auth)
app.include_router(search_query.router, prefix="/query", tags=["query"], dependencies=_auth)
app.include_router(persons.router, prefix="/persons", tags=["persons"], dependencies=_auth)
app.include_router(crawls.router, prefix="/crawls", tags=["crawls"], dependencies=_auth)
app.include_router(system.router, prefix="/system", tags=["system"])  # health only: public
app.include_router(system.admin_router, prefix="/system", tags=["system-admin"], dependencies=_auth)
app.include_router(ws.router, tags=["websocket"])
app.include_router(financial.router, prefix="/financial", tags=["financial"], dependencies=_auth)
app.include_router(marketing.router, prefix="/marketing", tags=["marketing"], dependencies=_auth)
app.include_router(graph.router, prefix="/graph", tags=["graph"], dependencies=_auth)
app.include_router(knowledge_graph.router, prefix="/kg", tags=["knowledge-graph"], dependencies=_auth)
app.include_router(dedup.router, prefix="/dedup", tags=["dedup"], dependencies=_auth)
app.include_router(enrichment.router, prefix="/enrich", tags=["enrichment"], dependencies=_auth)
app.include_router(patterns.router, prefix="/patterns", tags=["patterns"], dependencies=_auth)
app.include_router(behavioural.router, prefix="/behavioural", tags=["behavioural"], dependencies=_auth)
app.include_router(watchlist.router, prefix="/watchlist", tags=["watchlist"], dependencies=_auth)
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"], dependencies=_auth)
app.include_router(compliance.router, prefix="/compliance", tags=["compliance"], dependencies=_auth)
app.include_router(export.router, prefix="/export", tags=["export"], dependencies=_auth)
app.include_router(discovery.router, prefix="/discovery", tags=["discovery"], dependencies=_auth)
app.include_router(builder.router, prefix="/builder", tags=["builder"], dependencies=_auth)
app.include_router(relationships.router, prefix="/relationships", tags=["relationships"], dependencies=_auth)
