"""Financial/AML Intelligence Enricher — credit scoring, AML screening, fraud risk."""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import event_bus
from shared.models.address import Address
from shared.models.burner import BurnerAssessment
from shared.models.credit_risk import CreditRiskAssessment
from shared.models.criminal import CriminalRecord
from shared.models.darkweb import CryptoWallet, DarkwebMention
from shared.models.identifier import Identifier
from shared.models.watchlist import WatchlistMatch
from shared.models.wealth import WealthAssessment

logger = logging.getLogger(__name__)

# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class CreditScoreResult:
    score: int                           # 300–850 FICO-compatible
    confidence_interval: tuple[int, int]
    component_breakdown: dict[str, float]
    risk_category: str                   # excellent | good | fair | poor | very_poor


@dataclass
class AMLResult:
    risk_score: float                    # 0.0–1.0
    is_pep: bool
    sanctions_hits: list[dict[str, Any]]
    darkweb_mention_count: int
    risk_tier: str                       # low | medium | high | critical


@dataclass
class FraudRiskResult:
    fraud_score: float                   # 0.0–1.0
    fraud_indicators: list[str]
    tier: str                            # low | medium | high | critical


@dataclass
class FinancialProfile:
    person_id: str
    credit: CreditScoreResult
    aml: AMLResult
    fraud: FraudRiskResult
    assessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Helpers ──────────────────────────────────────────────────────────────────

_SCORE_MIN, _SCORE_MAX = 300, 850
_SCORE_RANGE = _SCORE_MAX - _SCORE_MIN
_WEIGHTS = {"payment_behavior": 0.30, "stability": 0.25, "wealth": 0.20,
            "utilization": 0.15, "trajectory": 0.10}
_CREDIT_TIERS = [(800, "excellent"), (740, "good"), (670, "fair"), (580, "poor"), (0, "very_poor")]
_AML_TIERS = [(0.75, "critical"), (0.50, "high"), (0.25, "medium"), (0.0, "low")]
_FRAUD_TIERS = [(0.75, "critical"), (0.50, "high"), (0.25, "medium"), (0.0, "low")]


def _tier(value: float, tiers: list[tuple[float, str]]) -> str:
    return next((label for threshold, label in tiers if value >= threshold), tiers[-1][1])


# ─── Alternative Credit Scorer ────────────────────────────────────────────────

class AlternativeCreditScorer:
    """Heuristic FICO-scale scorer. XGBoost can replace _score_* methods if available."""

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
        margin = 15 if signals.get("identifier_count", 0) >= 3 else 30
        ci = (max(_SCORE_MIN, raw - margin), min(_SCORE_MAX, raw + margin))
        return CreditScoreResult(
            score=raw,
            confidence_interval=ci,
            component_breakdown=components,
            risk_category=_tier(raw, _CREDIT_TIERS),
        )

    def _payment_behavior(self, s: dict) -> float:
        v = 1.0
        v -= min(0.40, s.get("criminal_felony_count", 0) * 0.15)
        v -= min(0.20, s.get("criminal_misdemeanor_count", 0) * 0.05)
        v -= min(0.25, s.get("watchlist_hit_count", 0) * 0.25)
        v -= 0.15 if s.get("pep_flag") else 0.0
        return max(0.0, v)

    def _stability(self, s: dict) -> float:
        v = 1.0
        v -= min(0.40, max(0, s.get("address_count", 1) - 5) * 0.08)
        v -= min(0.20, max(0, s.get("address_country_count", 1) - 2) * 0.10)
        v -= 0.20 if s.get("burner_flag") else 0.0
        return max(0.0, v)

    def _wealth(self, s: dict) -> float:
        band_score = {"ultra_high": 1.0, "high": 0.80, "upper_middle": 0.65,
                      "middle": 0.50, "lower_middle": 0.35, "low": 0.20}.get(
            s.get("wealth_band", "unknown"), 0.40)
        income_boost = min(0.20, ((s.get("income_estimate_usd") or 0) / 200_000) * 0.20)
        mixer_penalty = 0.15 if s.get("crypto_mixer_exposure") else 0.0
        return max(0.0, min(1.0, band_score + income_boost - mixer_penalty))

    def _utilization(self, s: dict) -> float:
        v = 1.0
        v -= min(0.50, s.get("darkweb_mention_count", 0) * 0.15)
        return max(0.0, v)

    def _trajectory(self, s: dict) -> float:
        v = 0.60
        if (s.get("crypto_total_volume_usd") or 0) > 100_000 and not s.get("crypto_mixer_exposure"):
            v += 0.20
        v -= min(0.40, s.get("criminal_felony_count", 0) * 0.20)
        return max(0.0, min(1.0, v))


# ─── AML Screener ─────────────────────────────────────────────────────────────

class AMLScreener:
    """Screen against sanctions, PEP lists, and darkweb/crypto signals."""

    def screen(
        self,
        watchlist_rows: list[WatchlistMatch],
        darkweb_rows: list[DarkwebMention],
        crypto_rows: list[CryptoWallet],
    ) -> AMLResult:
        risk = 0.0
        is_pep = False
        sanctions_hits: list[dict[str, Any]] = []

        for row in watchlist_rows:
            if row.list_type == "pep":
                is_pep = True
                risk = max(risk, 0.40)
            elif row.list_type in ("sanctions", "terrorist"):
                risk = max(risk, 0.90)
                sanctions_hits.append({"list_name": row.list_name, "list_type": row.list_type,
                                       "match_score": row.match_score, "match_name": row.match_name,
                                       "is_confirmed": row.is_confirmed})
            elif row.list_type == "fugitive":
                risk = max(risk, 0.70)
                sanctions_hits.append({"list_name": row.list_name, "list_type": row.list_type,
                                       "match_score": row.match_score, "match_name": row.match_name,
                                       "is_confirmed": row.is_confirmed})

        if darkweb_rows:
            avg_exp = sum(r.exposure_score for r in darkweb_rows) / len(darkweb_rows)
            risk = max(risk, min(0.60, avg_exp * 0.60))

        for wallet in crypto_rows:
            if wallet.mixer_exposure:
                risk = max(risk, 0.65)
            if wallet.risk_score > 0.7:
                risk = max(risk, wallet.risk_score * 0.70)

        risk = round(min(1.0, risk), 4)
        return AMLResult(
            risk_score=risk,
            is_pep=is_pep,
            sanctions_hits=sanctions_hits,
            darkweb_mention_count=len(darkweb_rows),
            risk_tier=_tier(risk, _AML_TIERS),
        )


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
        fraud_charges = [r for r in criminal_rows
                         if any(kw in (r.charge or "").lower() for kw in _FRAUD_KEYWORDS)]
        if fraud_charges:
            fs += min(0.40, len(fraud_charges) * 0.20)
            indicators.append(f"{len(fraud_charges)} fraud-related criminal records")

        # Crypto mixer
        mixer_wallets = [w for w in crypto_rows if w.mixer_exposure]
        if mixer_wallets:
            fs += min(0.30, len(mixer_wallets) * 0.15)
            indicators.append(f"{len(mixer_wallets)} wallet(s) with mixer exposure")

        fs = round(min(1.0, fs), 4)
        return FraudRiskResult(fraud_score=fs, fraud_indicators=indicators, tier=_tier(fs, _FRAUD_TIERS))


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class FinancialIntelligenceEngine:
    """Query all signals, run all scorers, persist results, emit event."""

    def __init__(self) -> None:
        self._credit = AlternativeCreditScorer()
        self._aml = AMLScreener()
        self._fraud = FraudRiskScorer()

    async def score_person(self, person_id: str, session: AsyncSession) -> FinancialProfile:
        pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id

        # Sequential DB queries — never asyncio.gather on same session
        watchlist = (await session.execute(
            select(WatchlistMatch).where(WatchlistMatch.person_id == pid)
        )).scalars().all()

        darkweb = (await session.execute(
            select(DarkwebMention).where(DarkwebMention.person_id == pid)
        )).scalars().all()

        crypto = (await session.execute(
            select(CryptoWallet).where(CryptoWallet.person_id == pid)
        )).scalars().all()

        addresses = (await session.execute(
            select(Address).where(Address.person_id == pid)
        )).scalars().all()

        identifiers = (await session.execute(
            select(Identifier).where(Identifier.person_id == pid)
        )).scalars().all()

        criminals = (await session.execute(
            select(CriminalRecord).where(CriminalRecord.person_id == pid)
        )).scalars().all()

        wealth_row = (await session.execute(
            select(WealthAssessment)
            .where(WealthAssessment.person_id == pid)
            .order_by(WealthAssessment.assessed_at.desc())
            .limit(1)
        )).scalars().first()

        identifier_ids = [i.id for i in identifiers]
        burner_rows = []
        if identifier_ids:
            burner_rows = (await session.execute(
                select(BurnerAssessment).where(BurnerAssessment.identifier_id.in_(identifier_ids))
            )).scalars().all()

        # Run scorers
        aml = self._aml.screen(list(watchlist), list(darkweb), list(crypto))
        fraud = self._fraud.score(list(addresses), list(identifiers),
                                  list(darkweb), list(criminals), list(crypto))

        signals: dict[str, Any] = {
            "criminal_felony_count": sum(1 for r in criminals if r.offense_level == "felony"),
            "criminal_misdemeanor_count": sum(1 for r in criminals if r.offense_level == "misdemeanor"),
            "watchlist_hit_count": len(watchlist),
            "darkweb_mention_count": len(darkweb),
            "address_count": len(addresses),
            "address_country_count": len({a.country_code for a in addresses if a.country_code}),
            "crypto_mixer_exposure": any(w.mixer_exposure for w in crypto),
            "crypto_total_volume_usd": sum(w.total_volume_usd for w in crypto),
            "wealth_band": wealth_row.wealth_band if wealth_row else "unknown",
            "income_estimate_usd": wealth_row.income_estimate_usd if wealth_row else None,
            "identifier_count": len(identifiers),
            "burner_flag": any(b.is_burner for b in burner_rows),
            "pep_flag": aml.is_pep,
        }
        credit = self._credit.score(signals)

        now = datetime.now(timezone.utc)

        # Persist credit risk assessment
        session.add(CreditRiskAssessment(
            person_id=pid,
            default_risk_score=round(1.0 - (credit.score - _SCORE_MIN) / _SCORE_RANGE, 4),
            risk_tier=credit.risk_category,
            gambling_weight=0.0,
            financial_distress_weight=round(fraud.fraud_score * 0.5, 4),
            court_judgment_weight=0.50 if any(
                r.disposition in ("guilty", "plea_deal") for r in criminals) else 0.0,
            burner_weight=0.0,
            synthetic_identity_weight=min(
                1.0, sum(1 for i in identifiers if i.confidence < 0.5) * 0.20),
            darkweb_weight=min(1.0, len(darkweb) * 0.15),
            criminal_weight=min(
                1.0, signals["criminal_felony_count"] * 0.25
                + signals["criminal_misdemeanor_count"] * 0.10),
            signal_breakdown={
                "credit_score": credit.score,
                "credit_components": credit.component_breakdown,
                "aml_risk_score": aml.risk_score,
                "aml_tier": aml.risk_tier,
                "fraud_score": fraud.fraud_score,
                "fraud_tier": fraud.tier,
                "fraud_indicators": fraud.fraud_indicators,
                "sanctions_hits": len(aml.sanctions_hits),
                "is_pep": aml.is_pep,
            },
            assessed_at=now,
            model_version="2.0",
        ))

        # Upsert WealthAssessment — update if exists, create if not
        vol_score = min(1.0, sum(w.total_volume_usd for w in crypto) / 1_000_000)
        mixer_penalty = 0.30 if any(w.mixer_exposure for w in crypto) else 0.0
        crypto_signal_val = max(0.0, vol_score - mixer_penalty)

        # Derive wealth_band from credit score
        if credit.score >= 750:
            derived_wealth_band = "high"
        elif credit.score >= 600:
            derived_wealth_band = "medium"
        else:
            derived_wealth_band = "low"

        # Derive income range estimates from stability and wealth signals
        stability_score = credit.component_breakdown.get("stability", 0.5)
        wealth_score = credit.component_breakdown.get("wealth", 0.5)
        base_income_min = round(20_000 + stability_score * 60_000 + wealth_score * 40_000, 2)
        base_income_max = round(base_income_min * 1.5, 2)

        if wealth_row:
            # Update existing record — only set wealth_band if no existing value is present
            if not wealth_row.wealth_band:
                wealth_row.wealth_band = derived_wealth_band
            wealth_row.income_estimate_usd = base_income_min
            wealth_row.crypto_signal = crypto_signal_val
            wealth_row.confidence = round(
                min(1.0, (credit.score - _SCORE_MIN) / _SCORE_RANGE), 4
            )
            wealth_row.assessed_at = now
        else:
            # Create new WealthAssessment record
            session.add(WealthAssessment(
                person_id=pid,
                wealth_band=derived_wealth_band,
                income_estimate_usd=base_income_min,
                net_worth_estimate_usd=base_income_max,
                confidence=round(
                    min(1.0, (credit.score - _SCORE_MIN) / _SCORE_RANGE), 4
                ),
                crypto_signal=crypto_signal_val,
                assessed_at=now,
            ))

        await session.flush()

        profile = FinancialProfile(person_id=str(pid), credit=credit,
                                   aml=aml, fraud=fraud, assessed_at=now)

        try:
            await event_bus.publish("enrichment", {
                "event": "financial_scored",
                "person_id": str(pid),
                "credit_score": credit.score,
                "risk_category": credit.risk_category,
                "aml_tier": aml.risk_tier,
                "fraud_tier": fraud.tier,
                "assessed_at": now.isoformat(),
            })
        except Exception:
            logger.warning("Event bus unavailable — financial_scored event not published")

        return profile
