"""Financial/AML Intelligence Enricher — credit scoring, AML screening, fraud risk."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from rapidfuzz.distance import JaroWinkler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import event_bus
from shared.models.address import Address
from shared.models.burner import BurnerAssessment
from shared.models.credit_risk import CreditRiskAssessment
from shared.models.criminal import CriminalRecord
from shared.models.darkweb import CryptoWallet, DarkwebMention
from shared.models.employment import EmploymentHistory
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.models.property import Property, PropertyMortgage
from shared.models.watchlist import WatchlistMatch
from shared.models.wealth import WealthAssessment

logger = logging.getLogger(__name__)

# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class CreditScoreResult:
    score: int  # 300–850 FICO-compatible
    confidence_interval: tuple[int, int]
    component_breakdown: dict[str, float]
    risk_category: str  # excellent | good | fair | poor | very_poor


@dataclass
class AMLResult:
    risk_score: float  # 0.0–1.0
    is_pep: bool
    sanctions_hits: list[dict[str, Any]]
    darkweb_mention_count: int
    risk_tier: str  # low | medium | high | critical
    fuzzy_match_count: int = 0


@dataclass
class FraudRiskResult:
    fraud_score: float  # 0.0–1.0
    fraud_indicators: list[str]
    tier: str  # low | medium | high | critical


@dataclass
class FinancialProfile:
    person_id: str
    credit: CreditScoreResult
    aml: AMLResult
    fraud: FraudRiskResult
    assessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ─── Helpers ──────────────────────────────────────────────────────────────────

_SCORE_MIN, _SCORE_MAX = 300, 850
_SCORE_RANGE = _SCORE_MAX - _SCORE_MIN
_WEIGHTS = {
    "payment_behavior": 0.30,
    "stability": 0.25,
    "wealth": 0.20,
    "utilization": 0.15,
    "trajectory": 0.10,
}
_CREDIT_TIERS = [(750, "excellent"), (700, "good"), (650, "fair"), (580, "poor"), (0, "very_poor")]
_AML_TIERS = [(0.75, "critical"), (0.50, "high"), (0.25, "medium"), (0.0, "low")]
_FRAUD_TIERS = [(0.75, "critical"), (0.50, "high"), (0.25, "medium"), (0.0, "low")]

# AML fuzzy matching thresholds
_FUZZY_HIGH = 0.92   # treat as potential hit — add to sanctions_hits
_FUZZY_LOW  = 0.85   # count as fuzzy signal but don't list as confirmed hit


def _tier(value: float, tiers: list[tuple[float, str]]) -> str:
    return next((label for threshold, label in tiers if value >= threshold), tiers[-1][1])


def _years_since(dt: date | datetime | None) -> float:
    """Return fractional years from dt to today. Returns 0 if dt is None."""
    if dt is None:
        return 0.0
    if isinstance(dt, datetime):
        dt = dt.date()
    return max(0.0, (date.today() - dt).days / 365.25)


from shared.utils import normalize_name as _normalize_name


# ─── Alternative Credit Scorer ────────────────────────────────────────────────


class AlternativeCreditScorer:
    """
    Five-factor alternative credit scorer (FICO-compatible 300-850).

    Component weights:
      payment_behavior  30% — public-record defaults: liens, judgments, bankruptcy
      stability         25% — address tenure, employment tenure, address churn
      wealth            20% — property equity, vehicle value, income band
      utilization       15% — known debt-to-income from public records
      trajectory        10% — improving or declining across all factors over time

    Falls back to heuristic signals when full public-record data is absent.
    XGBoost can replace the _score_* methods once labelled training data exists.
    """

    def score(self, signals: dict[str, Any]) -> CreditScoreResult:
        components = {
            "payment_behavior": self._payment_behavior(signals),
            "stability": self._stability(signals),
            "wealth": self._wealth(signals),
            "utilization": self._utilization(signals),
            "trajectory": self._trajectory(signals),
        }
        weighted = sum(components[k] * _WEIGHTS[k] for k in components)
        raw = max(_SCORE_MIN, min(_SCORE_MAX, _SCORE_MIN + int(weighted * _SCORE_RANGE)))
        # CI width narrows when we have more corroborating data points
        data_points = signals.get("data_point_count", 1)
        margin = max(10, 30 - data_points * 2)
        ci = (max(_SCORE_MIN, raw - margin), min(_SCORE_MAX, raw + margin))
        return CreditScoreResult(
            score=raw,
            confidence_interval=ci,
            component_breakdown={k: round(v, 4) for k, v in components.items()},
            risk_category=_tier(raw, _CREDIT_TIERS),
        )

    # ── Component scorers ─────────────────────────────────────────────────────

    def _payment_behavior(self, s: dict) -> float:
        """30% — public-record defaults, criminal financial records."""
        v = 1.0
        # Tax liens / civil judgments from public records
        v -= min(0.35, s.get("lien_count", 0) * 0.10)
        v -= min(0.20, s.get("judgment_count", 0) * 0.08)
        # Bankruptcy is severe
        if s.get("has_bankruptcy"):
            months_ago = s.get("months_since_bankruptcy", 0)
            # Full penalty up to 84 months (7 years), then fades
            penalty = max(0.0, 0.40 * (1.0 - months_ago / 84))
            v -= penalty
        # Evictions
        v -= min(0.15, s.get("eviction_count", 0) * 0.07)
        # Mortgage delinquency proxy
        v -= min(0.25, s.get("delinquent_mortgage_count", 0) * 0.12)
        # Existing criminal financial charges elevate risk
        v -= min(0.20, s.get("criminal_felony_count", 0) * 0.08)
        v -= min(0.10, s.get("criminal_misdemeanor_count", 0) * 0.03)
        v -= 0.10 if s.get("pep_flag") else 0.0
        v -= 0.15 if s.get("watchlist_hit_count", 0) > 0 else 0.0
        return max(0.0, v)

    def _stability(self, s: dict) -> float:
        """25% — address tenure, employment tenure, phone/address churn."""
        v = 1.0
        # Address churn penalty
        addr_count = s.get("address_count", 1)
        if addr_count > 8:
            v -= 0.40
        elif addr_count > 5:
            v -= 0.20
        elif addr_count > 3:
            v -= 0.10
        # Country diversity penalty (offshore complexity)
        v -= min(0.20, max(0, s.get("address_country_count", 1) - 2) * 0.10)
        # Employment stability bonus/penalty
        years_employed = s.get("years_at_current_employer", 0.0)
        if years_employed >= 5:
            v += 0.10  # long tenure — boost
        elif years_employed < 1:
            v -= 0.15  # very short — penalise
        # Address tenure at current address
        years_at_addr = s.get("years_at_current_address", 0.0)
        if years_at_addr >= 3:
            v += 0.05
        elif years_at_addr < 0.5:
            v -= 0.10
        # Burner phone
        v -= 0.20 if s.get("burner_flag") else 0.0
        return max(0.0, min(1.0, v))

    def _wealth(self, s: dict) -> float:
        """20% — property equity, vehicle value, income band, crypto."""
        # Base from wealth band
        band_score = {
            "ultra_high": 1.0,
            "high": 0.80,
            "upper_middle": 0.65,
            "middle": 0.50,
            "lower_middle": 0.35,
            "low": 0.20,
        }.get(s.get("wealth_band", "unknown"), 0.40)
        # Property equity bonus
        equity = s.get("property_equity_usd", 0) or 0
        equity_boost = min(0.20, equity / 500_000 * 0.20)
        # Income boost
        income = s.get("income_estimate_usd") or 0
        income_boost = min(0.15, income / 200_000 * 0.15)
        # Vehicle value modest signal
        vehicle_val = s.get("vehicle_value_usd", 0) or 0
        vehicle_boost = min(0.05, vehicle_val / 80_000 * 0.05)
        # Crypto mixer penalty
        mixer_penalty = 0.15 if s.get("crypto_mixer_exposure") else 0.0
        return max(0.0, min(1.0, band_score + equity_boost + income_boost + vehicle_boost - mixer_penalty))

    def _utilization(self, s: dict) -> float:
        """15% — debt-to-income from public records (mortgages + liens)."""
        v = 1.0
        known_debt = s.get("known_debt_usd", 0) or 0
        income = max(1, s.get("income_estimate_usd") or 1)
        dti = known_debt / income
        if dti > 5.0:
            v -= 0.50
        elif dti > 2.0:
            v -= 0.30
        elif dti > 1.0:
            v -= 0.15
        elif dti > 0.5:
            v -= 0.05
        # UCC filings (business debt)
        v -= min(0.20, s.get("ucc_filing_count", 0) * 0.04)
        # Darkweb credential exposure — proxy for financial stress
        v -= min(0.15, s.get("darkweb_mention_count", 0) * 0.05)
        return max(0.0, v)

    def _trajectory(self, s: dict) -> float:
        """10% — improving or declining across all factors."""
        v = 0.60
        # Positive: significant crypto wealth without mixer
        if (s.get("crypto_total_volume_usd") or 0) > 50_000 and not s.get("crypto_mixer_exposure"):
            v += 0.15
        # Positive: property value appreciation (proxy: owns property, no delinquency)
        if s.get("property_count", 0) > 0 and not s.get("delinquent_mortgage_count", 0):
            v += 0.10
        # Positive: employment stability improving
        if s.get("years_at_current_employer", 0) >= 3:
            v += 0.10
        # Negative: recent criminal activity
        v -= min(0.40, s.get("criminal_felony_count", 0) * 0.15)
        # Negative: recent lien/judgment (within last 24 months)
        v -= min(0.20, s.get("recent_lien_count", 0) * 0.10)
        return max(0.0, min(1.0, v))


# ─── AML Screener ─────────────────────────────────────────────────────────────


class AMLScreener:
    """
    Screen a person against sanctions lists, PEP flags, adverse media, and
    darkweb/crypto signals.

    Fuzzy name matching uses Jaro-Winkler similarity (rapidfuzz) to catch
    transliterations and typos across all WatchlistMatch rows in the DB.
    """

    def screen(
        self,
        person_name: str | None,
        watchlist_rows: list[WatchlistMatch],
        darkweb_rows: list[DarkwebMention],
        crypto_rows: list[CryptoWallet],
        adverse_media_score: float = 0.0,
        jurisdiction_risk: float = 0.0,
        entity_complexity: float = 0.0,
    ) -> AMLResult:
        is_pep = False
        sanctions_hits: list[dict[str, Any]] = []
        fuzzy_match_count = 0

        # Component scores (0.0–1.0 each)
        sanctions_match = 0.0
        pep_component = 0.0
        adverse_component = 0.0
        jurisdiction_component = 0.0

        norm_name = _normalize_name(person_name) if person_name else ""

        for row in watchlist_rows:
            # Direct DB match (already confirmed by crawler)
            if row.list_type == "pep":
                is_pep = True
                pep_component = max(pep_component, 1.0)
            elif row.list_type in ("sanctions", "terrorist"):
                sanctions_match = max(sanctions_match, 1.0)
                sanctions_hits.append(self._hit_dict(row, "direct"))
            elif row.list_type == "fugitive":
                sanctions_match = max(sanctions_match, 0.80)
                sanctions_hits.append(self._hit_dict(row, "direct"))

            # Fuzzy name check against the matched_name on the watchlist row
            if norm_name and row.match_name:
                sim = JaroWinkler.normalized_similarity(
                    norm_name, _normalize_name(row.match_name)
                )
                if sim >= _FUZZY_HIGH and row.list_type not in ("pep",):
                    fuzzy_match_count += 1
                    if not any(h.get("match_name") == row.match_name for h in sanctions_hits):
                        sanctions_match = max(sanctions_match, sim * 0.80)
                        sanctions_hits.append(self._hit_dict(row, "fuzzy", sim))
                elif sim >= _FUZZY_LOW:
                    fuzzy_match_count += 1
                    sanctions_match = max(sanctions_match, sim * 0.50)

        # Darkweb / crypto boost sanctions_match component
        if darkweb_rows:
            avg_exp = sum(r.exposure_score for r in darkweb_rows) / len(darkweb_rows)
            sanctions_match = max(sanctions_match, min(0.60, avg_exp * 0.60))

        for wallet in crypto_rows:
            if wallet.mixer_exposure:
                sanctions_match = max(sanctions_match, 0.65)
            if wallet.risk_score > 0.7:
                sanctions_match = max(sanctions_match, wallet.risk_score * 0.70)

        # Adverse media (0.0–1.0)
        adverse_component = min(1.0, adverse_media_score)

        # Jurisdiction risk (0.0–1.0)
        jurisdiction_component = min(1.0, jurisdiction_risk)

        # Weighted composite per spec:
        #   sanctions_match * 0.40 + pep_status * 0.25 +
        #   adverse_media * 0.20 + jurisdiction_risk * 0.15
        risk = (
            sanctions_match * 0.40
            + pep_component * 0.25
            + adverse_component * 0.20
            + jurisdiction_component * 0.15
        )

        # Entity complexity bonus (additive, small)
        if entity_complexity > 0:
            risk = min(1.0, risk + entity_complexity * 0.10)

        risk = round(min(1.0, risk), 4)
        return AMLResult(
            risk_score=risk,
            is_pep=is_pep,
            sanctions_hits=sanctions_hits,
            darkweb_mention_count=len(darkweb_rows),
            risk_tier=_tier(risk, _AML_TIERS),
            fuzzy_match_count=fuzzy_match_count,
        )

    @staticmethod
    def _hit_dict(row: WatchlistMatch, match_type: str, similarity: float = 1.0) -> dict[str, Any]:
        return {
            "list_name": row.list_name,
            "list_type": row.list_type,
            "match_score": row.match_score,
            "match_name": row.match_name,
            "is_confirmed": row.is_confirmed,
            "match_type": match_type,
            "jaro_winkler_similarity": round(similarity, 4),
        }


# ─── Fraud Risk Scorer ────────────────────────────────────────────────────────

_FRAUD_KEYWORDS = ("fraud", "identity theft", "forgery", "wire", "impersonation")


class FraudRiskScorer:
    """Score fraud risk from address velocity, identity signals, and darkweb exposure."""

    def score(
        self,
        address_rows: list[Address],
        identifier_rows: list[Identifier],
        darkweb_rows: list[DarkwebMention],
        criminal_rows: list[CriminalRecord],
        crypto_rows: list[CryptoWallet],
    ) -> FraudRiskResult:
        fs = 0.0
        indicators: list[str] = []

        # Address velocity
        n_addr = len(address_rows)
        if n_addr > 8:
            fs += 0.20
            indicators.append(f"high address velocity: {n_addr}")
        elif n_addr > 5:
            fs += 0.10
            indicators.append(f"elevated address velocity: {n_addr}")

        n_countries = len({a.country_code for a in address_rows if a.country_code})
        if n_countries > 3:
            fs += 0.10
            indicators.append(f"multi-country presence: {n_countries} countries")

        # Identity document inconsistencies
        low_conf = [i for i in identifier_rows if i.confidence < 0.5]
        if low_conf:
            fs += min(0.25, len(low_conf) * 0.08)
            indicators.append(f"{len(low_conf)} low-confidence identifiers")

        type_counts: dict[str, int] = {}
        for i in identifier_rows:
            type_counts[i.type] = type_counts.get(i.type, 0) + 1
        dupes = [t for t, c in type_counts.items() if c > 1]
        if dupes:
            fs += min(0.30, len(dupes) * 0.15)
            indicators.append(f"duplicate identifier types: {dupes}")

        # Darkweb exposure
        if darkweb_rows:
            high_sev = [r for r in darkweb_rows if r.severity in ("critical", "high")]
            if high_sev:
                fs += min(0.35, len(high_sev) * 0.12)
                indicators.append(f"{len(high_sev)} high-severity darkweb mentions")
            else:
                fs += min(0.15, len(darkweb_rows) * 0.05)
                indicators.append(f"{len(darkweb_rows)} darkweb mentions")

        # Fraud-related criminal charges
        fraud_charges = [
            r
            for r in criminal_rows
            if any(kw in (r.charge or "").lower() for kw in _FRAUD_KEYWORDS)
        ]
        if fraud_charges:
            fs += min(0.40, len(fraud_charges) * 0.20)
            indicators.append(f"{len(fraud_charges)} fraud-related criminal records")

        # Crypto mixer
        mixer_wallets = [w for w in crypto_rows if w.mixer_exposure]
        if mixer_wallets:
            fs += min(0.30, len(mixer_wallets) * 0.15)
            indicators.append(f"{len(mixer_wallets)} wallet(s) with mixer exposure")

        fs = round(min(1.0, fs), 4)
        return FraudRiskResult(
            fraud_score=fs, fraud_indicators=indicators, tier=_tier(fs, _FRAUD_TIERS)
        )


# ─── Orchestrator ─────────────────────────────────────────────────────────────

# Keywords that signal financial distress in criminal charge text
_LIEN_KEYWORDS = ("lien", "tax lien", "mechanic's lien")
_JUDGMENT_KEYWORDS = ("judgment", "civil judgment", "monetary judgment", "garnishment")
_EVICTION_KEYWORDS = ("eviction", "unlawful detainer", "forcible entry")
_BANKRUPTCY_KEYWORDS = ("bankruptcy", "bankrupt", "chapter 7", "chapter 13", "chapter 11")


class FinancialIntelligenceEngine:
    """Query all signals, run all scorers, persist results, emit event."""

    def __init__(self) -> None:
        self._credit = AlternativeCreditScorer()
        self._aml = AMLScreener()
        self._fraud = FraudRiskScorer()

    async def score_person(self, person_id: str, session: AsyncSession) -> FinancialProfile:
        pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id

        # ── Sequential DB queries — never asyncio.gather on same session ──────
        person_row = await session.get(Person, pid)

        watchlist = (
            (await session.execute(select(WatchlistMatch).where(WatchlistMatch.person_id == pid)))
            .scalars()
            .all()
        )

        darkweb = (
            (await session.execute(select(DarkwebMention).where(DarkwebMention.person_id == pid)))
            .scalars()
            .all()
        )

        crypto = (
            (await session.execute(select(CryptoWallet).where(CryptoWallet.person_id == pid)))
            .scalars()
            .all()
        )

        addresses = (
            (await session.execute(select(Address).where(Address.person_id == pid))).scalars().all()
        )

        identifiers = (
            (await session.execute(select(Identifier).where(Identifier.person_id == pid)))
            .scalars()
            .all()
        )

        criminals = (
            (await session.execute(select(CriminalRecord).where(CriminalRecord.person_id == pid)))
            .scalars()
            .all()
        )

        employment = (
            (
                await session.execute(
                    select(EmploymentHistory).where(EmploymentHistory.person_id == pid)
                )
            )
            .scalars()
            .all()
        )

        properties = (
            (await session.execute(select(Property).where(Property.person_id == pid)))
            .scalars()
            .all()
        )

        # Collect mortgage/lien data from property records
        all_property_ids = [p.id for p in properties]
        mortgages: list[PropertyMortgage] = []
        if all_property_ids:
            mortgages = (
                (
                    await session.execute(
                        select(PropertyMortgage).where(
                            PropertyMortgage.property_id.in_(all_property_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )

        wealth_row = (
            (
                await session.execute(
                    select(WealthAssessment)
                    .where(WealthAssessment.person_id == pid)
                    .order_by(WealthAssessment.assessed_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

        identifier_ids = [i.id for i in identifiers]
        burner_rows = []
        if identifier_ids:
            burner_rows = (
                (
                    await session.execute(
                        select(BurnerAssessment).where(
                            BurnerAssessment.identifier_id.in_(identifier_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )

        # ── Derive public-record financial signals ─────────────────────────────
        lien_charges = [
            r for r in criminals if any(kw in (r.charge or "").lower() for kw in _LIEN_KEYWORDS)
        ]
        judgment_charges = [
            r
            for r in criminals
            if any(kw in (r.charge or "").lower() for kw in _JUDGMENT_KEYWORDS)
        ]
        eviction_charges = [
            r
            for r in criminals
            if any(kw in (r.charge or "").lower() for kw in _EVICTION_KEYWORDS)
        ]
        bankruptcy_charges = [
            r
            for r in criminals
            if any(kw in (r.charge or "").lower() for kw in _BANKRUPTCY_KEYWORDS)
        ]

        # Most-recent bankruptcy date
        months_since_bankruptcy = 999
        for bc in bankruptcy_charges:
            if bc.offense_date:
                mo = _years_since(bc.offense_date) * 12
                months_since_bankruptcy = min(months_since_bankruptcy, int(mo))

        # Current employment tenure
        current_jobs = [e for e in employment if e.is_current and e.started_at]
        years_at_employer = 0.0
        if current_jobs:
            years_at_employer = _years_since(current_jobs[0].started_at)

        # Income estimate (job salary → wealth → fallback)
        income_usd: float | None = None
        for e in current_jobs:
            if e.estimated_salary_usd:
                income_usd = e.estimated_salary_usd
                break
        if income_usd is None and wealth_row:
            income_usd = wealth_row.income_estimate_usd

        # Property equity
        property_equity = 0.0
        property_market_value = 0.0
        for p in properties:
            val = p.current_market_value_usd or p.current_assessed_value_usd or 0
            property_market_value += val
        mortgage_balance_total = sum(
            m.original_amount or 0 for m in mortgages if m.lien_position in (None, 1, "first")
        )
        property_equity = max(0.0, property_market_value - mortgage_balance_total)

        # Known debt: mortgages + lien amounts (approximate from criminal records)
        known_debt = mortgage_balance_total

        # Current address tenure
        sorted_addrs = sorted(
            [a for a in addresses if a.updated_at], key=lambda a: a.updated_at, reverse=True
        )
        years_at_addr = _years_since(sorted_addrs[0].updated_at) if sorted_addrs else 0.0
        # Invert: updated_at on an address means we last confirmed it, so larger = more stable
        years_at_addr = max(0.0, 3.0 - years_at_addr)  # crude proxy

        # Vehicle value from wealth assessment
        vehicle_value = 0.0
        if wealth_row and hasattr(wealth_row, "vehicle_signal"):
            vehicle_value = wealth_row.vehicle_signal * 40_000  # rough proxy

        # UCC filing count proxy (business-debt activity)
        ucc_count = sum(1 for r in criminals if "ucc" in (r.charge or "").lower())

        # Adverse media / jurisdiction from person denormalised columns
        adverse_media_score = getattr(person_row, "adverse_media_score", 0.0) if person_row else 0.0

        # Jurisdiction risk: penalise if person has addresses in FATF grey/black list countries
        # (simple heuristic — full FATF list lookup is in dedicated crawler)
        _HIGH_RISK_COUNTRIES = {
            "AF", "MM", "KP", "IR", "SY", "YE", "LY", "SO", "SS", "CF",
            "CD", "ML", "NI", "PK", "PH", "UA", "RU",
        }
        country_codes = {a.country_code for a in addresses if a.country_code}
        jurisdiction_risk = 0.30 if country_codes & _HIGH_RISK_COUNTRIES else 0.0

        # Entity complexity: multiple nationalities, multiple countries, multiple properties
        entity_complexity = min(1.0, (
            max(0, len(country_codes) - 2) * 0.10
            + max(0, len(properties) - 2) * 0.05
        ))

        # ── Build signals dict for credit scorer ──────────────────────────────
        signals: dict[str, Any] = {
            # Payment behavior (30%)
            "lien_count": len(lien_charges),
            "judgment_count": len(judgment_charges),
            "has_bankruptcy": len(bankruptcy_charges) > 0,
            "months_since_bankruptcy": months_since_bankruptcy if bankruptcy_charges else 999,
            "eviction_count": len(eviction_charges),
            "delinquent_mortgage_count": sum(
                1 for m in mortgages if getattr(m, "is_delinquent", False)
            ),
            "criminal_felony_count": sum(1 for r in criminals if r.offense_level == "felony"),
            "criminal_misdemeanor_count": sum(
                1 for r in criminals if r.offense_level == "misdemeanor"
            ),
            "watchlist_hit_count": len(watchlist),
            # Stability (25%)
            "address_count": len(addresses),
            "address_country_count": len(country_codes),
            "years_at_current_employer": round(years_at_employer, 2),
            "years_at_current_address": round(years_at_addr, 2),
            "burner_flag": any(b.burner_score >= 0.40 for b in burner_rows),
            # Wealth (20%)
            "wealth_band": wealth_row.wealth_band if wealth_row else "unknown",
            "property_equity_usd": round(property_equity, 2),
            "income_estimate_usd": income_usd,
            "vehicle_value_usd": round(vehicle_value, 2),
            "property_count": len(properties),
            "crypto_mixer_exposure": any(w.mixer_exposure for w in crypto),
            "crypto_total_volume_usd": sum(w.total_volume_usd for w in crypto),
            # Utilization (15%)
            "known_debt_usd": round(known_debt, 2),
            "ucc_filing_count": ucc_count,
            "darkweb_mention_count": len(darkweb),
            # Trajectory (10%)
            "recent_lien_count": sum(
                1 for r in lien_charges
                if r.offense_date and _years_since(r.offense_date) <= 2.0
            ),
            # Meta
            "identifier_count": len(identifiers),
            "data_point_count": (
                len(addresses) + len(identifiers) + len(criminals) + len(properties)
                + len(employment) + len(crypto)
            ),
            "pep_flag": False,  # updated after AML screening below
        }

        # ── Run AML screen first so pep_flag feeds credit scorer ───────────────
        person_name = person_row.full_name if person_row else None
        aml = self._aml.screen(
            person_name=person_name,
            watchlist_rows=list(watchlist),
            darkweb_rows=list(darkweb),
            crypto_rows=list(crypto),
            adverse_media_score=adverse_media_score,
            jurisdiction_risk=jurisdiction_risk,
            entity_complexity=entity_complexity,
        )
        signals["pep_flag"] = aml.is_pep

        # ── Run credit and fraud scorers ───────────────────────────────────────
        credit = self._credit.score(signals)
        fraud = self._fraud.score(
            list(addresses), list(identifiers), list(darkweb), list(criminals), list(crypto)
        )

        now = datetime.now(UTC)

        # ── Persist CreditRiskAssessment ──────────────────────────────────────
        session.add(
            CreditRiskAssessment(
                person_id=pid,
                default_risk_score=round(1.0 - (credit.score - _SCORE_MIN) / _SCORE_RANGE, 4),
                risk_tier=credit.risk_category,
                gambling_weight=0.0,
                financial_distress_weight=round(fraud.fraud_score * 0.5, 4),
                court_judgment_weight=0.50
                if any(r.disposition in ("guilty", "plea_deal") for r in criminals)
                else 0.0,
                burner_weight=0.0,
                synthetic_identity_weight=min(
                    1.0, sum(1 for i in identifiers if i.confidence < 0.5) * 0.20
                ),
                darkweb_weight=min(1.0, len(darkweb) * 0.15),
                criminal_weight=min(
                    1.0,
                    signals["criminal_felony_count"] * 0.25
                    + signals["criminal_misdemeanor_count"] * 0.10,
                ),
                signal_breakdown={
                    "credit_score": credit.score,
                    "credit_components": credit.component_breakdown,
                    "aml_risk_score": aml.risk_score,
                    "aml_tier": aml.risk_tier,
                    "aml_fuzzy_matches": aml.fuzzy_match_count,
                    "fraud_score": fraud.fraud_score,
                    "fraud_tier": fraud.tier,
                    "fraud_indicators": fraud.fraud_indicators,
                    "sanctions_hits": len(aml.sanctions_hits),
                    "is_pep": aml.is_pep,
                    "property_equity_usd": signals["property_equity_usd"],
                    "known_debt_usd": signals["known_debt_usd"],
                    "lien_count": signals["lien_count"],
                    "judgment_count": signals["judgment_count"],
                },
                assessed_at=now,
                model_version="3.0",
            )
        )

        # ── Upsert WealthAssessment ────────────────────────────────────────────
        vol_score = min(1.0, sum(w.total_volume_usd for w in crypto) / 1_000_000)
        mixer_penalty = 0.30 if any(w.mixer_exposure for w in crypto) else 0.0
        crypto_signal_val = max(0.0, vol_score - mixer_penalty)

        if credit.score >= 750:
            derived_wealth_band = "high"
        elif credit.score >= 600:
            derived_wealth_band = "medium"
        else:
            derived_wealth_band = "low"

        stability = credit.component_breakdown.get("stability", 0.5)
        wealth_comp = credit.component_breakdown.get("wealth", 0.5)
        base_income_min = round(20_000 + stability * 60_000 + wealth_comp * 40_000, 2)
        # Override with real salary data if available
        if income_usd:
            base_income_min = income_usd

        if wealth_row:
            if not wealth_row.wealth_band:
                wealth_row.wealth_band = derived_wealth_band
            wealth_row.income_estimate_usd = base_income_min
            wealth_row.crypto_signal = crypto_signal_val
            wealth_row.confidence = round(min(1.0, (credit.score - _SCORE_MIN) / _SCORE_RANGE), 4)
            wealth_row.assessed_at = now
        else:
            session.add(
                WealthAssessment(
                    person_id=pid,
                    wealth_band=derived_wealth_band,
                    income_estimate_usd=base_income_min,
                    net_worth_estimate_usd=round(base_income_min * 1.5 + property_equity, 2),
                    confidence=round(min(1.0, (credit.score - _SCORE_MIN) / _SCORE_RANGE), 4),
                    crypto_signal=crypto_signal_val,
                    assessed_at=now,
                )
            )

        await session.flush()

        # ── Write denormalised scores back to Person ──────────────────────────
        if person_row:
            person_row.default_risk_score = round(
                1.0 - (credit.score - _SCORE_MIN) / _SCORE_RANGE, 4
            )
            person_row.darkweb_exposure = round(min(1.0, len(darkweb) * 0.15), 4)
            person_row.behavioural_risk = round(fraud.fraud_score, 4)
            person_row.alt_credit_score = credit.score
            person_row.alt_credit_tier = credit.risk_category
            person_row.aml_risk_score = aml.risk_score
            person_row.aml_risk_tier = aml.risk_tier
            if aml.is_pep:
                person_row.pep_status = True
            if aml.sanctions_hits:
                person_row.is_sanctioned = True
            await session.flush()

        profile = FinancialProfile(
            person_id=str(pid), credit=credit, aml=aml, fraud=fraud, assessed_at=now
        )

        try:
            await event_bus.publish(
                "enrichment",
                {
                    "event": "financial_scored",
                    "person_id": str(pid),
                    "credit_score": credit.score,
                    "risk_category": credit.risk_category,
                    "aml_tier": aml.risk_tier,
                    "fraud_tier": fraud.tier,
                    "assessed_at": now.isoformat(),
                },
            )
        except Exception:
            logger.warning("Event bus unavailable — financial_scored event not published")

        return profile
