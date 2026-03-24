import importlib
import pkgutil
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes import crawls, persons, search, search_query, system, ws
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

# ── Static & Templates ────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── UI Routes ─────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def ui_index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/ui/persons", include_in_schema=False)
async def ui_persons(request: Request, session: AsyncSession = DbDep):
    # Fetch persons with some stats
    q = select(Person).order_by(Person.created_at.desc()).limit(100)
    result = await session.execute(q)
    persons_raw = result.scalars().all()

    persons_list = []
    for p in persons_raw:
        # Count identifiers and social profiles for stats
        id_count = (await session.execute(select(Identifier).where(Identifier.person_id == p.id))).scalars().all()
        sp_count = (await session.execute(select(SocialProfile).where(SocialProfile.person_id == p.id))).scalars().all()

        persons_list.append({
            "id": str(p.id),
            "full_name": p.full_name,
            "identifier_count": len(id_count),
            "platform_count": len(sp_count),
            "default_risk_score": p.default_risk_score,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return templates.TemplateResponse(request, "persons.html", {"persons": persons_list})


@app.get("/ui/person/{person_id}", include_in_schema=False)
async def ui_person(request: Request, person_id: str, session: AsyncSession = DbDep):
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        return templates.TemplateResponse(request, "index.html", {"error": "Invalid UUID"})

    p = await session.get(Person, uid)
    if not p:
        return templates.TemplateResponse(request, "index.html", {"error": "Person not found"})

    # Fetch all related data
    async def _fetch(model):
        r = await session.execute(select(model).where(model.person_id == uid))
        return r.scalars().all()

    idents = await _fetch(Identifier)
    profiles = await _fetch(SocialProfile)
    aliases = await _fetch(Alias)
    addresses = await _fetch(Address)
    employment = await _fetch(EmploymentHistory)
    darkweb = await _fetch(DarkwebMention)
    watchlist = await _fetch(WatchlistMatch)
    breaches = await _fetch(BreachRecord)

    # Burner assessment (one-to-one with primary phone identifier usually)
    burner = None
    phone_ident = next((i for i in idents if i.type == "phone"), None)
    if phone_ident:
        br = await session.execute(select(BurnerAssessment).where(BurnerAssessment.identifier_id == phone_ident.id))
        burner = br.scalar_one_or_none()

    # Behavioural profile
    beh_q = await session.execute(select(BehaviouralProfile).where(BehaviouralProfile.person_id == uid))
    behavioural = beh_q.scalar_one_or_none()

    return templates.TemplateResponse(request, "person.html", {
        "person": p,
        "identifiers": idents,
        "social_profiles": profiles,
        "aliases": aliases,
        "addresses": addresses,
        "employment": employment,
        "darkweb": darkweb,
        "watchlist": watchlist,
        "breaches": breaches,
        "burner": burner,
        "behavioural": behavioural,
    })


@app.get("/ui/activity", include_in_schema=False)
async def ui_activity(request: Request, session: AsyncSession = DbDep):
    q = select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(100)
    result = await session.execute(q)
    jobs = result.scalars().all()
    return templates.TemplateResponse(request, "activity.html", {"jobs": jobs})


# ── API Routes ────────────────────────────────────────────────────────────────

app.include_router(search.router,       prefix="/search",  tags=["search"])
app.include_router(search_query.router, prefix="/query",   tags=["query"])
app.include_router(persons.router,      prefix="/persons", tags=["persons"])
app.include_router(crawls.router,       prefix="/crawls",  tags=["crawls"])
app.include_router(system.router,       prefix="/system",  tags=["system"])
app.include_router(ws.router,                              tags=["websocket"])
