import re
import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from modules.crawlers.registry import CRAWLER_REGISTRY
from modules.dispatcher.dispatcher import dispatch_job
from shared.constants import SeedType
from shared.events import event_bus
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.schemas.progress import EventType

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
        "username_maigret",
        "email_socialscan",
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
        # Phone OSINT
        "phone_phoneinfoga",
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
        # Email OSINT
        "email_socialscan",
        "email_dehashed",
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
        # People OSINT
        "people_phonebook",
        "people_intelx",
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
        # Domain OSINT
        "people_phonebook",
        "people_intelx",
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
    # Pivot-only types — dispatched by pivot enricher, never from API input directly
    SeedType.INSTAGRAM_HANDLE: ["instagram", "username_maigret", "username_sherlock"],
    SeedType.TWITTER_HANDLE: ["twitter", "username_maigret", "username_sherlock"],
    SeedType.LINKEDIN_URL: ["linkedin"],
}


def _auto_detect_type(value: str) -> SeedType:
    value_clean = value.strip()
    value_lower = value_clean.lower()

    if re.match(r"^\+?\d[\d\s\-().]{7,15}$", value_lower):
        return SeedType.PHONE

    if re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", value_lower):
        return SeedType.EMAIL

    # Ethereum address
    if re.match(r"^0x[a-fA-F0-9]{40}$", value_clean):
        return SeedType.CRYPTO_WALLET

    # Bitcoin mainnet address (P2PKH / P2SH / bech32)
    if re.match(r"^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$", value_clean) or re.match(
        r"^bc1[a-zA-Z0-9]{6,87}$", value_clean
    ):
        return SeedType.CRYPTO_WALLET

    # Generic long hex hash (Monero, etc.)
    if re.match(r"^[a-f0-9]{64}$", value_lower):
        return SeedType.CRYPTO_WALLET

    # IPv4 / IPv6
    if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", value_lower) or re.match(
        r"^[0-9a-fA-F:]+:[0-9a-fA-F:]+$", value_lower
    ):
        return SeedType.IP_ADDRESS

    # Domain (has a dot, no spaces)
    if (
        re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$", value_lower)
        and "." in value_lower
    ):
        return SeedType.DOMAIN

    # Multi-word string → full name
    if " " in value_clean:
        return SeedType.FULL_NAME

    return SeedType.USERNAME


# ── Request / Response schemas ────────────────────────────────────────────────


class SearchRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    seed_type: SeedType | None = None
    context: str = Field(
        default="general",
        pattern=r"^(general|risk|wealth|identity)$",
    )
    max_depth: int = Field(default=2, ge=1, le=5)
    priority: str = Field(
        default="normal",
        pattern=r"^(high|normal|low)$",
    )

    @field_validator("value")
    @classmethod
    def sanitize_value(cls, v: str) -> str:
        """Sanitize input to prevent injection attacks.

        Allows: alphanumeric, spaces, hyphens, apostrophes, periods, @, +,
        underscores, colons (IPv6), and forward slashes (URLs).
        Strips HTML tags and common injection patterns.
        """
        v = v.strip()
        if not v:
            raise ValueError("Search value cannot be empty")
        # Strip HTML tags
        v = re.sub(r"<[^>]+>", "", v)
        # Strip shell injection patterns
        v = re.sub(r"[$`\\]", "", v)
        # Allow chars needed for: names, emails, phones, crypto addresses,
        # IPs, domains, usernames
        allowed = re.compile(
            r"[^a-zA-Z0-9\s\-\'.@+_:./()#]"
        )
        v = allowed.sub("", v)
        v = v.strip()
        if not v:
            raise ValueError("Search value contains no valid characters after sanitization")
        return v


class CandidatePerson(BaseModel):
    person_id: str
    full_name: str | None
    date_of_birth: str | None
    nationality: str | None
    identifier_count: int
    risk_score: float


class SearchResponse(BaseModel):
    person_id: str
    seed_type: str
    platforms_queued: list[str] = []
    job_count: int = 0
    message: str
    requires_disambiguation: bool = False
    candidates: list[CandidatePerson] = []


class BatchSearchRequest(BaseModel):
    seeds: list[SearchRequest] = Field(..., min_length=1, max_length=50)


class BatchSearchResponse(BaseModel):
    results: list[SearchResponse]
    total_jobs: int


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_candidates(value: str, session: AsyncSession) -> list[CandidatePerson]:
    """Return all Person records whose full_name matches (case-insensitive)."""
    result = await session.execute(select(Person).where(Person.full_name.ilike(value.strip())))
    persons = result.scalars().all()
    candidates = []
    for p in persons:
        count_result = await session.execute(
            select(func.count()).select_from(Identifier).where(Identifier.person_id == p.id)
        )
        ident_count = count_result.scalar() or 0
        candidates.append(
            CandidatePerson(
                person_id=str(p.id),
                full_name=p.full_name,
                date_of_birth=p.date_of_birth.isoformat() if p.date_of_birth else None,
                nationality=p.nationality,
                identifier_count=ident_count,
                risk_score=p.default_risk_score,
            )
        )
    return candidates


async def _process_single(req: SearchRequest, session: AsyncSession) -> SearchResponse:
    seed_type = req.seed_type or _auto_detect_type(req.value)
    priority = req.priority if req.priority in ("high", "normal", "low") else "normal"

    # ── FULL_NAME: check for disambiguation before creating ───────────────────
    if seed_type == SeedType.FULL_NAME:
        candidates = await _get_candidates(req.value, session)
        if len(candidates) > 1:
            return SearchResponse(
                person_id="",
                seed_type=seed_type.value,
                message=f"Multiple persons found for '{req.value}'. Please select one.",
                requires_disambiguation=True,
                candidates=candidates,
            )

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

    # Publish search_started so the SSE progress endpoint knows total scraper count
    if event_bus.is_connected and queued:
        try:
            await event_bus.publish(
                "progress",
                {
                    "event_type": EventType.SEARCH_STARTED,
                    "search_id": str(person_id),
                    "total_scrapers": len(queued),
                    "scrapers": queued,
                },
            )
        except Exception:
            pass

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


class CandidatesResponse(BaseModel):
    value: str
    seed_type: str
    candidates: list[CandidatePerson]
    count: int


@router.get("/candidates", response_model=CandidatesResponse)
async def search_candidates(
    value: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description="Search value (name, email, username, etc.)",
    ),
    seed_type: str | None = Query(default=None, description="Force seed type"),
    session: AsyncSession = DbDep,
):
    """
    Return matching persons for a value without creating any new records.

    For FULL_NAME, returns all persons with that exact name (case-insensitive).
    For other seed types, returns person linked to a matching identifier.
    Used by the frontend disambiguation screen.
    """
    detected = SeedType(seed_type) if seed_type else _auto_detect_type(value)

    if detected == SeedType.FULL_NAME:
        candidates = await _get_candidates(value, session)
    else:
        norm_val = value.strip().lower()
        result = await session.execute(
            select(Identifier).where(
                Identifier.type == detected.value,
                Identifier.normalized_value == norm_val,
            )
        )
        idents = result.scalars().all()
        candidates = []
        for ident in idents:
            if not ident.person_id:
                continue
            person = await session.get(Person, ident.person_id)
            if not person:
                continue
            count_result = await session.execute(
                select(func.count())
                .select_from(Identifier)
                .where(Identifier.person_id == person.id)
            )
            ident_count = count_result.scalar() or 0
            candidates.append(
                CandidatePerson(
                    person_id=str(person.id),
                    full_name=person.full_name,
                    date_of_birth=person.date_of_birth.isoformat()
                    if person.date_of_birth
                    else None,
                    nationality=person.nationality,
                    identifier_count=ident_count,
                    risk_score=person.default_risk_score,
                )
            )

    return CandidatesResponse(
        value=value,
        seed_type=detected.value,
        candidates=candidates,
        count=len(candidates),
    )
