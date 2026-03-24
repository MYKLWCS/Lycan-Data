import re
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from modules.crawlers.registry import CRAWLER_REGISTRY
from modules.dispatcher.dispatcher import dispatch_job
from shared.constants import SeedType
from shared.models.identifier import Identifier
from shared.models.person import Person

router = APIRouter()

# Seed type → applicable platform crawlers
SEED_PLATFORM_MAP: dict[SeedType, list[str]] = {
    SeedType.USERNAME: [
        # Social platforms (username-based only — NOT phone-based messengers)
        "instagram",
        "twitter",
        "reddit",
        "github",
        "youtube",
        "tiktok",
        "linkedin",
        "facebook",
        "snapchat",
        "pinterest",
        "discord",
        "mastodon",
        "twitch",
        "steam",
        # Username sweep
        "username_sherlock",
        # Dark web / paste username lookup
        "darkweb_ahmia",
        "paste_pastebin",
        "paste_ghostbin",
        "paste_psbdmp",
        "telegram_dark",
    ],
    SeedType.PHONE: [
        # Carrier & enrichment
        "phone_carrier",
        "phone_fonefinder",
        "phone_truecaller",
        "phone_numlookup",
        # Messaging confirmation
        "whatsapp",
        "telegram",
    ],
    SeedType.EMAIL: [
        # Breach & leak databases
        "email_hibp",
        "email_holehe",
        "email_leakcheck",
        "email_breach",
        # Reputation & validation
        "email_emailrep",
        "email_mx_validator",
        # Dark web / paste exposure
        "darkweb_ahmia",
        "darkweb_torch",
        "paste_pastebin",
        "paste_ghostbin",
        "paste_psbdmp",
    ],
    SeedType.FULL_NAME: [
        # People-search aggregators
        "whitepages",
        "fastpeoplesearch",
        "truepeoplesearch",
        "people_thatsthem",
        # Law enforcement / missing persons
        "people_interpol",
        "people_namus",
        "people_usmarshals",
        # Sanctions & watchlists — all major lists
        "sanctions_ofac",
        "sanctions_un",
        "sanctions_fbi",
        "sanctions_eu",
        "sanctions_uk",
        "sanctions_opensanctions",
        "sanctions_fatf",
        # Court & legal
        "court_courtlistener",
        "court_state",
        "bankruptcy_pacer",
        # Corporate filings
        "company_opencorporates",
        "company_sec",
        "company_companies_house",
        # Public government databases
        "public_npi",
        "public_faa",
        "public_nsopw",
        "gov_fec",
        "gov_propublica",
        "gov_usaspending",
        # Property & vehicle
        "vehicle_ownership",
        "property_zillow",
        # Media & web
        "news_search",
        "obituary_search",
        # Dark web name sweep
        "darkweb_ahmia",
        "darkweb_torch",
        "paste_pastebin",
        "paste_psbdmp",
    ],
    SeedType.DOMAIN: [
        "domain_whois",
        "domain_harvester",
        # Cyber intel on the domain
        "cyber_crt",
        "cyber_urlscan",
        "cyber_wayback",
        "cyber_virustotal",
        "cyber_alienvault",
    ],
    SeedType.CRYPTO_WALLET: [
        "crypto_bitcoin",
        "crypto_ethereum",
        "crypto_blockchair",
        "crypto_polygonscan",
    ],
    SeedType.IP_ADDRESS: [
        "ip_whois",
        "ip_geolocation",
        "ip_threatfeed",
        # Threat intelligence
        "cyber_abuseipdb",
        "cyber_shodan",
        "cyber_greynoise",
        "cyber_alienvault",
        "geo_ip",
    ],
    SeedType.NATIONAL_ID: [
        "sanctions_ofac",
        "sanctions_un",
        "sanctions_eu",
        "sanctions_uk",
        "sanctions_opensanctions",
    ],
    SeedType.COMPANY_REG: [
        "company_opencorporates",
        "company_sec",
        "company_companies_house",
        "gov_fdic",
        "gov_gleif",
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
    if re.match(r"^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$", value) or re.match(
        r"^bc1[a-z0-9]{6,87}$", value
    ):
        return SeedType.CRYPTO_WALLET

    # Generic long hex hash (Monero, etc.)
    if re.match(r"^[a-f0-9]{64}$", value, re.IGNORECASE):
        return SeedType.CRYPTO_WALLET

    # IPv4 / IPv6
    if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", value) or re.match(
        r"^[0-9a-fA-F:]+:[0-9a-fA-F:]+$", value
    ):
        return SeedType.IP_ADDRESS

    # Domain (has a dot, no spaces)
    if (
        re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$", value)
        and "." in value
    ):
        return SeedType.DOMAIN

    # Multi-word string → full name
    if " " in value.strip():
        return SeedType.FULL_NAME

    return SeedType.USERNAME


# ── Request / Response schemas ────────────────────────────────────────────────


class SearchRequest(BaseModel):
    value: str
    seed_type: SeedType | None = None
    context: str = "general"  # "risk", "wealth", "identity", "general"
    max_depth: int = 2
    priority: str = "normal"  # "high", "normal", "low"


class SearchResponse(BaseModel):
    person_id: str
    seed_type: str
    platforms_queued: list[str] = []
    job_count: int = 0
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

    # ── Check for existing identifier ────────────────────────────────────────
    norm_val = req.value.strip().lower()
    q = (
        select(Identifier)
        .where(Identifier.type == seed_type.value, Identifier.normalized_value == norm_val)
        .limit(1)
    )
    existing_ident = (await session.execute(q)).scalar_one_or_none()

    if existing_ident and existing_ident.person_id:
        person_id = existing_ident.person_id
    else:
        # Create person record — set full_name when searching by name
        person = Person(
            id=uuid.uuid4(),
            full_name=req.value.strip() if seed_type == SeedType.FULL_NAME else None,
        )
        session.add(person)
        await session.flush()
        person_id = person.id

        if not existing_ident:
            # Create seed identifier
            ident = Identifier(
                id=uuid.uuid4(),
                person_id=person_id,
                type=seed_type.value,
                value=req.value,
                normalized_value=norm_val,
                confidence=1.0,
                is_primary=True,
                meta={"context": req.context, "max_depth": req.max_depth},
            )
            session.add(ident)
        else:
            existing_ident.person_id = person_id

    await session.commit()

    # Enqueue crawl jobs for all matching registered platforms
    from shared.constants import CrawlStatus
    from shared.models.crawl import CrawlJob

    platforms = SEED_PLATFORM_MAP.get(seed_type, [])
    queued: list[str] = []
    for platform in platforms:
        if platform in CRAWLER_REGISTRY:
            job = CrawlJob(
                id=uuid.uuid4(),
                person_id=person_id,
                status=CrawlStatus.PENDING.value,
                job_type="crawl",
                seed_identifier=req.value,
                meta={"platform": platform},
            )
            session.add(job)
            await session.flush()  # Ensure ID is generated/synced

            await dispatch_job(
                platform=platform,
                identifier=req.value,
                person_id=str(person_id),
                priority=priority,
                job_id=str(job.id),
            )
            queued.append(platform)

    await session.commit()

    return SearchResponse(
        person_id=str(person_id),
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
