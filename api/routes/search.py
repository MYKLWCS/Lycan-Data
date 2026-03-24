import re
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.constants import SeedType
from shared.models.person import Person
from shared.models.identifier import Identifier
from modules.crawlers.registry import CRAWLER_REGISTRY
from modules.dispatcher.dispatcher import dispatch_job

router = APIRouter()

# Seed type → applicable platform crawlers
SEED_PLATFORM_MAP: dict[SeedType, list[str]] = {
    SeedType.USERNAME: [
        "instagram", "twitter", "reddit", "github", "youtube", "tiktok",
        "linkedin", "facebook", "snapchat", "pinterest", "discord",
        "telegram", "whatsapp", "username_sherlock",
    ],
    SeedType.PHONE: [
        "phone_carrier", "phone_fonefinder", "phone_truecaller", "whatsapp", "telegram",
    ],
    SeedType.EMAIL: [
        "email_hibp", "email_holehe",
    ],
    SeedType.FULL_NAME: [
        "whitepages", "fastpeoplesearch", "truepeoplesearch",
        "sanctions_ofac", "sanctions_un", "sanctions_fbi",
        "court_courtlistener", "company_opencorporates", "company_sec",
        "public_npi", "public_faa", "public_nsopw",
        "vehicle_ownership", "news_search", "obituary_search",
    ],
    SeedType.DOMAIN: [
        "domain_whois", "domain_harvester",
    ],
    SeedType.CRYPTO_WALLET: [
        "crypto_bitcoin", "crypto_ethereum", "crypto_blockchair",
    ],
    SeedType.IP_ADDRESS: [
        "ip_whois", "ip_geolocation", "ip_threatfeed",
    ],
    SeedType.NATIONAL_ID: [
        "sanctions_ofac", "sanctions_un",
    ],
    SeedType.COMPANY_REG: [
        "company_opencorporates", "company_sec",
    ],
}


def _auto_detect_type(value: str) -> SeedType:
    value = value.strip()

    if re.match(r"^\+?\d[\d\s\-().]{7,15}$", value):
        return SeedType.PHONE

    if re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", value):
        return SeedType.EMAIL

    # Ethereum address
    if re.match(r"^0x[a-fA-F0-9]{40}$", value):
        return SeedType.CRYPTO_WALLET

    # Bitcoin mainnet address (P2PKH / P2SH / bech32)
    if re.match(r"^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$", value) or re.match(r"^bc1[a-z0-9]{6,87}$", value):
        return SeedType.CRYPTO_WALLET

    # Generic long hex hash (Monero, etc.)
    if re.match(r"^[a-f0-9]{64}$", value, re.IGNORECASE):
        return SeedType.CRYPTO_WALLET

    # IPv4 / IPv6
    if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", value) or re.match(r"^[0-9a-fA-F:]+:[0-9a-fA-F:]+$", value):
        return SeedType.IP_ADDRESS

    # Domain (has a dot, no spaces)
    if re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$", value) and "." in value:
        return SeedType.DOMAIN

    # Multi-word string → full name
    if " " in value.strip():
        return SeedType.FULL_NAME

    return SeedType.USERNAME


# ── Request / Response schemas ────────────────────────────────────────────────

class SearchRequest(BaseModel):
    value: str
    seed_type: SeedType | None = None
    context: str = "general"   # "risk", "wealth", "identity", "general"
    max_depth: int = 2
    priority: str = "normal"   # "high", "normal", "low"


class SearchResponse(BaseModel):
    person_id: str
    seed_type: str
    platforms_queued: list[str]
    job_count: int
    message: str


class BatchSearchRequest(BaseModel):
    seeds: list[SearchRequest]


class BatchSearchResponse(BaseModel):
    results: list[SearchResponse]
    total_jobs: int


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _process_single(req: SearchRequest, session: AsyncSession) -> SearchResponse:
    seed_type = req.seed_type or _auto_detect_type(req.value)
    priority = req.priority if req.priority in ("high", "normal", "low") else "normal"

    # Create person record
    person = Person(id=uuid.uuid4())
    session.add(person)

    # Create seed identifier
    ident = Identifier(
        id=uuid.uuid4(),
        person_id=person.id,
        type=seed_type.value,
        value=req.value,
        normalized_value=req.value.strip().lower(),
        confidence=1.0,
        is_primary=True,
        meta={"context": req.context, "max_depth": req.max_depth},
    )
    session.add(ident)
    await session.commit()

    # Enqueue crawl jobs for all matching registered platforms
    platforms = SEED_PLATFORM_MAP.get(seed_type, [])
    queued: list[str] = []
    for platform in platforms:
        if platform in CRAWLER_REGISTRY:
            await dispatch_job(
                platform=platform,
                identifier=req.value,
                person_id=str(person.id),
                priority=priority,
            )
            queued.append(platform)

    return SearchResponse(
        person_id=str(person.id),
        seed_type=seed_type.value,
        platforms_queued=queued,
        job_count=len(queued),
        message=f"Search initiated. {len(queued)} scraper(s) queued.",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest, session: AsyncSession = DbDep):
    """Submit a single identifier search. Auto-detects seed type if not provided."""
    return await _process_single(req, session)


@router.post("/batch", response_model=BatchSearchResponse)
async def search_batch(req: BatchSearchRequest, session: AsyncSession = DbDep):
    """Submit multiple identifier searches in one call."""
    results: list[SearchResponse] = []
    for seed in req.seeds:
        result = await _process_single(seed, session)
        results.append(result)

    return BatchSearchResponse(
        results=results,
        total_jobs=sum(r.job_count for r in results),
    )
