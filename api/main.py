import importlib
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import crawls, persons, search, search_query, system
from shared.db import engine  # noqa: F401 — imported to validate config on startup
from shared.events import event_bus


def _import_all_crawlers() -> None:
    """Auto-import every module under modules.crawlers so they self-register."""
    import modules.crawlers as pkg

    for _, name, _ in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"modules.crawlers.{name}")
        except Exception:
            pass  # Broken crawlers don't abort startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    _import_all_crawlers()
    try:
        await event_bus.connect()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("EventBus could not connect — continuing without Redis")
    # Connect Tor control ports (non-fatal if Tor isn't running)
    try:
        from shared.tor import tor_manager
        await tor_manager.connect_all()
    except Exception:
        pass
    # Ensure MeiliSearch index exists
    try:
        from modules.search.meili_indexer import meili_indexer
        await meili_indexer.setup_index()
    except Exception:
        pass
    yield
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

app.include_router(search.router,       prefix="/search",  tags=["search"])
app.include_router(search_query.router, prefix="/query",   tags=["query"])
app.include_router(persons.router,      prefix="/persons", tags=["persons"])
app.include_router(crawls.router,       prefix="/crawls",  tags=["crawls"])
app.include_router(system.router,       prefix="/system",  tags=["system"])
