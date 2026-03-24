import asyncio
import importlib
import logging
import pkgutil
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

from api.routes import crawls, dedup, enrichment, financial, graph, marketing, patterns, persons, search, search_query, system, ws
from api.routes import behavioural, watchlist, alerts, compliance, export
from api.deps import DbDep
from shared.db import engine
from shared.events import event_bus
from shared.models.person import Person, Alias
from shared.models.identifier import Identifier
from shared.models.social_profile import SocialProfile
from shared.models.address import Address
from shared.models.employment import EmploymentHistory
from shared.models.darkweb import DarkwebMention
from shared.models.watchlist import WatchlistMatch
from shared.models.breach import BreachRecord
from shared.models.burner import BurnerAssessment
from shared.models.behavioural import BehaviouralProfile
from shared.models.crawl import CrawlJob
from shared.models.criminal import CriminalRecord
from shared.models.identity_document import IdentityDocument, CreditProfile
from shared.models.identifier_history import IdentifierHistory


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
    except Exception:
        pass
    # Initialize rate limiter and circuit breaker with shared Redis client
    try:
        from shared.rate_limiter import init_rate_limiter
        from shared.circuit_breaker import init_circuit_breaker
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static & SPA ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

from fastapi.responses import FileResponse

@app.get("/", include_in_schema=False)
async def ui_index():
    return FileResponse("static/index.html")

@app.get("/ui/{path:path}", include_in_schema=False)
async def ui_redirect(path: str):
    """Redirect old /ui/* routes to the SPA hash router."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/#/{path}")

# ── API Routes ────────────────────────────────────────────────────────────────

app.include_router(search.router,       prefix="/search",  tags=["search"])
app.include_router(search_query.router, prefix="/query",   tags=["query"])
app.include_router(persons.router,      prefix="/persons", tags=["persons"])
app.include_router(crawls.router,       prefix="/crawls",  tags=["crawls"])
app.include_router(system.router,       prefix="/system",  tags=["system"])
app.include_router(ws.router,                              tags=["websocket"])
app.include_router(financial.router, prefix="/financial",  tags=["financial"])
app.include_router(marketing.router, prefix="/marketing",  tags=["marketing"])
app.include_router(graph.router,     prefix="/graph",      tags=["graph"])
app.include_router(dedup.router,       prefix="/dedup",      tags=["dedup"])
app.include_router(enrichment.router,  prefix="/enrich",    tags=["enrichment"])
app.include_router(patterns.router,    prefix="/patterns",  tags=["patterns"])
app.include_router(behavioural.router, prefix="/behavioural", tags=["behavioural"])
app.include_router(watchlist.router,   prefix="/watchlist",   tags=["watchlist"])
app.include_router(alerts.router,      prefix="/alerts",      tags=["alerts"])
app.include_router(compliance.router,  prefix="/compliance",  tags=["compliance"])
app.include_router(export.router,      prefix="/export",      tags=["export"])
