"""Marketing Tags Intelligence Enricher — consumer tag classification engine."""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import event_bus
from shared.models.address import Address
from shared.models.behavioural import BehaviouralProfile
from shared.models.criminal import CriminalRecord
from shared.models.darkweb import CryptoWallet, DarkwebMention
from shared.models.employment import EmploymentHistory
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.models.social_profile import SocialProfile
from shared.models.wealth import WealthAssessment

logger = logging.getLogger(__name__)

# ─── Tag Taxonomy ─────────────────────────────────────────────────────────────

class LendingTag(StrEnum):
    TITLE_LOAN_CANDIDATE     = "title_loan_candidate"
    PAYDAY_LOAN_CANDIDATE    = "payday_loan_candidate"
    PERSONAL_LOAN_CANDIDATE  = "personal_loan_candidate"
    MORTGAGE_READY           = "mortgage_ready"
    REFINANCE_CANDIDATE      = "refinance_candidate"
    AUTO_LOAN_CANDIDATE      = "auto_loan_candidate"
    DEBT_CONSOLIDATION       = "debt_consolidation"
    CREDIT_CARD_CANDIDATE    = "credit_card_candidate"


class InvestmentTag(StrEnum):
    CRYPTO_INVESTOR       = "crypto_investor"
    REAL_ESTATE_INVESTOR  = "real_estate_investor"
    RETIREMENT_PLANNING   = "retirement_planning"


class BehaviouralTag(StrEnum):
    ACTIVE_GAMBLER      = "active_gambler"
    CASINO_GAMBLER      = "casino_gambler"
    SPORTS_BETTOR       = "sports_bettor"
    ONLINE_GAMBLER      = "online_gambler"
    TRAVEL_ENTHUSIAST   = "travel_enthusiast"
    FITNESS_ENTHUSIAST  = "fitness_enthusiast"
    LUXURY_BUYER        = "luxury_buyer"
    BARGAIN_HUNTER      = "bargain_hunter"


class LifeStageTag(StrEnum):
    NEW_PARENT         = "new_parent"
    NEWLY_MARRIED      = "newly_married"
    RECENTLY_DIVORCED  = "recently_divorced"
    RECENT_MOVER       = "recent_mover"
    RECENT_GRADUATE    = "recent_graduate"
    RETIRING_SOON      = "retiring_soon"


# ─── Thresholds ───────────────────────────────────────────────────────────────

_THRESHOLDS: dict[str, float] = {
    LendingTag.TITLE_LOAN_CANDIDATE:    0.70,
    InvestmentTag.CRYPTO_INVESTOR:      0.70,
    InvestmentTag.REAL_ESTATE_INVESTOR: 0.70,
    LifeStageTag.RECENT_MOVER:          0.70,
    LifeStageTag.NEW_PARENT:            0.70,
    BehaviouralTag.ACTIVE_GAMBLER:      0.65,
    BehaviouralTag.LUXURY_BUYER:        0.65,
    LifeStageTag.RETIRING_SOON:         0.65,
}

_HIGH_INCOME_TITLES = (
    "ceo", "cto", "cfo", "coo", "cso", "president", "founder",
    "director", "vp ", "vice president", "managing director",
    "doctor", "dr.", "physician", "surgeon", "attorney", "lawyer",
    "engineer", "partner",
)

_GAMBLING_KEYWORDS = ("gambling", "casino", "poker", "betting", "bet", "slots", "wager")
_CRYPTO_KEYWORDS = ("crypto", "bitcoin", "btc", "eth", "ethereum", "defi", "nft", "web3", "blockchain")
_PARENTING_KEYWORDS = ("parent", "baby", "infant", "toddler", "newborn", "mom", "dad", "family", "diaper", "nursery")
_FINANCIAL_CRIME_KEYWORDS = ("fraud", "lien", "judgment", "garnishment", "embezzlement", "theft", "forgery")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TagResult:
    tag: str
    confidence: float
    reasoning: list[str]
    scored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BorrowerProfile:
    score: int                     # 0-100
    tier: str                      # prime | near_prime | subprime | deep_subprime
    applicable_products: list[str]
    signals: list[str]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _compute_age(dob: date | None) -> int | None:
    if dob is None:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _social_text(profiles: list[SocialProfile]) -> str:
    parts: list[str] = []
    for p in profiles:
        if p.handle:
            parts.append(p.handle.lower())
        if p.bio:
            parts.append(p.bio.lower())
    return " ".join(parts)


def _darkweb_text(mentions: list[DarkwebMention]) -> str:
    return " ".join(
        (m.mention_context or "").lower() for m in mentions
    )


# ─── Tag Scorers ──────────────────────────────────────────────────────────────

def _score_title_loan(
    addresses: list[Address],
    criminals: list[CriminalRecord],
    wealth: WealthAssessment | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    # Vehicle signal — via wealth vehicle_signal proxy
    if wealth and wealth.vehicle_signal > 0.3:
        score += 0.4
        reasons.append(f"vehicle signal present (score: {wealth.vehicle_signal:.2f})")

    # Financial crimes or liens in criminal records
    fin_crimes = [
        r for r in criminals
        if any(kw in (r.charge or "").lower() for kw in _FINANCIAL_CRIME_KEYWORDS)
    ]
    if fin_crimes:
        score += 0.3
        reasons.append(f"{len(fin_crimes)} financial crime/lien record(s)")

    # Low wealth band
    if wealth and wealth.wealth_band in ("low", "lower_middle"):
        score += 0.2
        reasons.append(f"wealth band: {wealth.wealth_band}")

    # Address instability — >3 addresses recorded
    if len(addresses) > 3:
        score += 0.1
        reasons.append(f"address instability: {len(addresses)} addresses on record")

    return _clamp(score), reasons


def _score_active_gambler(
    darkweb: list[DarkwebMention],
    socials: list[SocialProfile],
    behavioural: BehaviouralProfile | None,
    age: int | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    dw_text = _darkweb_text(darkweb)
    if any(kw in dw_text for kw in _GAMBLING_KEYWORDS):
        score += 0.3
        reasons.append("gambling keywords in darkweb mentions")

    social_text = _social_text(socials)
    if any(kw in social_text for kw in _GAMBLING_KEYWORDS):
        score += 0.2
        reasons.append("gambling-related handles/bios on social profiles")

    if behavioural and behavioural.gambling_score > 0.3:
        score += 0.2
        reasons.append(f"behavioural gambling score: {behavioural.gambling_score:.2f}")

    if age is not None and 25 <= age <= 55:
        score += 0.2
        reasons.append(f"age {age} in prime gambler demographic (25-55)")

    return _clamp(score), reasons


def _score_crypto_investor(
    crypto_wallets: list[CryptoWallet],
    identifiers: list[Identifier],
    socials: list[SocialProfile],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if crypto_wallets:
        score += 0.5
        reasons.append(f"{len(crypto_wallets)} crypto wallet(s) on darkweb/records")

    crypto_ids = [i for i in identifiers if "crypto" in i.type.lower() or "wallet" in i.type.lower()]
    if crypto_ids:
        score += 0.3
        reasons.append(f"{len(crypto_ids)} crypto-type identifier(s)")

    social_text = _social_text(socials)
    if any(kw in social_text for kw in _CRYPTO_KEYWORDS):
        score += 0.2
        reasons.append("crypto-related handles/bios in social profiles")

    return _clamp(score), reasons


def _score_real_estate_investor(
    addresses: list[Address],
    employment: list[EmploymentHistory],
    wealth: WealthAssessment | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    # Proxy: multiple distinct addresses (non-current = likely owns more than one property)
    distinct_cities = len({(a.city, a.state_province) for a in addresses if a.city})
    if distinct_cities >= 2:
        score += 0.5
        reasons.append(f"{distinct_cities} distinct address locations on record")

    re_employers = [
        e for e in employment
        if e.industry and "real estate" in e.industry.lower()
    ]
    if re_employers:
        score += 0.3
        reasons.append(f"real estate industry employment: {re_employers[0].employer_name}")

    if wealth and wealth.wealth_band in ("high", "ultra_high"):
        score += 0.2
        reasons.append(f"wealth band: {wealth.wealth_band}")

    return _clamp(score), reasons


def _score_recent_mover(
    addresses: list[Address],
    identifiers: list[Identifier],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    recent_addrs = [
        a for a in addresses
        if a.updated_at and a.updated_at >= cutoff
    ]
    if recent_addrs:
        score += 0.8
        reasons.append(f"{len(recent_addrs)} address record(s) updated in last 90 days")

    # Identifier history proxy — address-type identifiers recently updated
    recent_id_addrs = [
        i for i in identifiers
        if "address" in i.type.lower() and i.updated_at and i.updated_at >= cutoff
    ]
    if recent_id_addrs:
        score += 0.2
        reasons.append(f"{len(recent_id_addrs)} address-type identifier(s) updated in last 90 days")

    return _clamp(score), reasons


def _score_luxury_buyer(
    wealth: WealthAssessment | None,
    employment: list[EmploymentHistory],
    addresses: list[Address],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if wealth and wealth.wealth_band in ("high", "ultra_high"):
        score += 0.5
        reasons.append(f"wealth band: {wealth.wealth_band}")

    current_jobs = [e for e in employment if e.is_current and e.job_title]
    for job in current_jobs:
        title_lower = (job.job_title or "").lower()
        if any(kw in title_lower for kw in _HIGH_INCOME_TITLES):
            score += 0.3
            reasons.append(f"high-income job title: {job.job_title}")
            break

    if len(addresses) >= 2:
        score += 0.2
        reasons.append(f"multiple property records: {len(addresses)} addresses")

    return _clamp(score), reasons


def _score_retiring_soon(
    age: int | None,
    employment: list[EmploymentHistory],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if age is not None and 60 <= age <= 67:
        score += 0.7
        reasons.append(f"age {age} in pre-retirement range (60-67)")

    # Long-tenure current employment
    long_tenure = [
        e for e in employment
        if e.is_current and e.started_at and
        (date.today() - e.started_at).days >= 365 * 15
    ]
    if long_tenure:
        years = round((date.today() - long_tenure[0].started_at).days / 365, 1)
        score += 0.3
        reasons.append(f"long employment tenure: {years} years at {long_tenure[0].employer_name or 'current employer'}")

    return _clamp(score), reasons


def _score_new_parent(
    behavioural: BehaviouralProfile | None,
    age: int | None,
    addresses: list[Address],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if behavioural:
        interests_text = " ".join(behavioural.interests).lower()
        if any(kw in interests_text for kw in _PARENTING_KEYWORDS):
            score += 0.5
            reasons.append("parenting/family signals in behavioural interests")

    if age is not None and 25 <= age <= 40:
        score += 0.3
        reasons.append(f"age {age} in new-parent range (25-40)")

    # Recent address change as proxy for getting more space
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    recent = [a for a in addresses if a.updated_at and a.updated_at >= cutoff]
    if recent:
        score += 0.2
        reasons.append("recent address change in last 180 days")

    return _clamp(score), reasons


# ─── High Interest Borrower Scorer ────────────────────────────────────────────

_BORROWER_TIERS = [
    (75, "prime",        ["personal_loan", "mortgage", "auto_loan", "credit_card"]),
    (60, "near_prime",   ["personal_loan", "auto_loan", "credit_card", "refinance"]),
    (40, "subprime",     ["title_loan", "payday_loan", "personal_loan", "auto_loan"]),
    (0,  "deep_subprime", ["title_loan", "payday_loan"]),
]


class HighInterestBorrowerScorer:
    """Detect subprime/high-interest borrower profiles."""

    def score(
        self,
        criminals: list[CriminalRecord],
        addresses: list[Address],
        employment: list[EmploymentHistory],
        wealth: WealthAssessment | None,
    ) -> BorrowerProfile:
        raw = 100
        signals: list[str] = []

        # Liens and judgments
        liens = [r for r in criminals if any(
            kw in (r.charge or "").lower() for kw in ("lien", "judgment", "garnishment")
        )]
        if liens:
            raw -= len(liens) * 10
            signals.append(f"{len(liens)} lien/judgment record(s)")

        # Bankruptcy
        bankruptcies = [r for r in criminals if "bankrupt" in (r.charge or "").lower()]
        if bankruptcies:
            raw -= 20
            signals.append("bankruptcy record present")

        # Address instability
        if len(addresses) > 5:
            raw -= 15
            signals.append(f"high address instability: {len(addresses)} addresses")
        elif len(addresses) > 3:
            raw -= 7
            signals.append(f"moderate address instability: {len(addresses)} addresses")

        # Employment tenure — penalize gaps or no current employment
        current = [e for e in employment if e.is_current]
        if not current:
            raw -= 10
            signals.append("no current employment record")
        else:
            for emp in current:
                if emp.started_at:
                    tenure_years = (date.today() - emp.started_at).days / 365
                    if tenure_years < 1:
                        raw -= 10
                        signals.append(f"short employment tenure: {tenure_years:.1f} years")
                    elif tenure_years >= 5:
                        raw += 5
                        signals.append(f"stable employment tenure: {tenure_years:.1f} years")
                    break

        # Wealth band adjustments
        if wealth:
            band_adj = {
                "ultra_high": 10, "high": 7, "upper_middle": 3,
                "middle": 0, "lower_middle": -5, "low": -10,
            }.get(wealth.wealth_band, 0)
            if band_adj != 0:
                raw += band_adj
                signals.append(f"wealth band adjustment ({wealth.wealth_band}): {band_adj:+d}")

        clamped = max(0, min(100, raw))
        tier, products = next(
            (t, p) for threshold, t, p in _BORROWER_TIERS if clamped >= threshold
        )
        return BorrowerProfile(score=clamped, tier=tier, applicable_products=products, signals=signals)


# ─── Marketing Tags Engine ─────────────────────────────────────────────────────

class MarketingTagsEngine:
    """Query available DB data and assign marketing intelligence tags to a person."""

    def __init__(self) -> None:
        self._borrower_scorer = HighInterestBorrowerScorer()

    async def tag_person(self, person_id: str, session: AsyncSession) -> list[TagResult]:
        pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id

        # Sequential DB queries — never asyncio.gather on same session
        person = (await session.execute(
            select(Person).where(Person.id == pid)
        )).scalars().first()

        addresses = list((await session.execute(
            select(Address).where(Address.person_id == pid)
        )).scalars().all())

        employment = list((await session.execute(
            select(EmploymentHistory).where(EmploymentHistory.person_id == pid)
        )).scalars().all())

        criminals = list((await session.execute(
            select(CriminalRecord).where(CriminalRecord.person_id == pid)
        )).scalars().all())

        darkweb = list((await session.execute(
            select(DarkwebMention).where(DarkwebMention.person_id == pid)
        )).scalars().all())

        crypto_wallets = list((await session.execute(
            select(CryptoWallet).where(CryptoWallet.person_id == pid)
        )).scalars().all())

        identifiers = list((await session.execute(
            select(Identifier).where(Identifier.person_id == pid)
        )).scalars().all())

        socials = list((await session.execute(
            select(SocialProfile).where(SocialProfile.person_id == pid)
        )).scalars().all())

        behavioural = (await session.execute(
            select(BehaviouralProfile).where(BehaviouralProfile.person_id == pid)
        )).scalars().first()

        wealth = (await session.execute(
            select(WealthAssessment)
            .where(WealthAssessment.person_id == pid)
            .order_by(WealthAssessment.assessed_at.desc())
            .limit(1)
        )).scalars().first()

        # Derived values
        dob = person.date_of_birth if person else None
        age = _compute_age(dob)
        now = datetime.now(timezone.utc)

        # Run all scorers
        scoring_map: list[tuple[str, float, list[str]]] = []

        s, r = _score_title_loan(addresses, criminals, wealth)
        scoring_map.append((LendingTag.TITLE_LOAN_CANDIDATE, s, r))

        s, r = _score_active_gambler(darkweb, socials, behavioural, age)
        scoring_map.append((BehaviouralTag.ACTIVE_GAMBLER, s, r))

        s, r = _score_crypto_investor(crypto_wallets, identifiers, socials)
        scoring_map.append((InvestmentTag.CRYPTO_INVESTOR, s, r))

        s, r = _score_real_estate_investor(addresses, employment, wealth)
        scoring_map.append((InvestmentTag.REAL_ESTATE_INVESTOR, s, r))

        s, r = _score_recent_mover(addresses, identifiers)
        scoring_map.append((LifeStageTag.RECENT_MOVER, s, r))

        s, r = _score_luxury_buyer(wealth, employment, addresses)
        scoring_map.append((BehaviouralTag.LUXURY_BUYER, s, r))

        s, r = _score_retiring_soon(age, employment)
        scoring_map.append((LifeStageTag.RETIRING_SOON, s, r))

        s, r = _score_new_parent(behavioural, age, addresses)
        scoring_map.append((LifeStageTag.NEW_PARENT, s, r))

        # Filter by threshold and build results
        results: list[TagResult] = []
        for tag, confidence, reasoning in scoring_map:
            threshold = _THRESHOLDS.get(tag, 0.65)
            if confidence >= threshold and reasoning:
                results.append(TagResult(
                    tag=tag,
                    confidence=round(confidence, 4),
                    reasoning=reasoning,
                    scored_at=now,
                ))

        try:
            await event_bus.publish("enrichment", {
                "event": "marketing_tagged",
                "person_id": str(pid),
                "tag_count": len(results),
            })
        except Exception:
            logger.warning("Event bus unavailable — marketing_tagged event not published")

        return results
