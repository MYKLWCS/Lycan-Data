"""Commercial Tagger — PersonSignals assembly and CommercialTaggerDaemon."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timezone, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.enrichers.marketing_tags import (
    _THRESHOLDS,
    BankingTag,
    InsuranceTag,
    LendingTag,
    TagResult,
    WealthTag,
    _compute_age,
    _score_auto_loan_candidate,
    _score_banking_basic,
    _score_banking_premium,
    _score_debt_consolidation,
    _score_high_net_worth,
    _score_insurance_auto,
    _score_insurance_health,
    _score_insurance_life,
    _score_mortgage_candidate,
    _score_payday_loan_candidate,
    _score_personal_loan_candidate,
    _score_refinance_candidate,
)
from shared.db import AsyncSessionLocal
from shared.models.behavioural import BehaviouralProfile
from shared.models.criminal import CriminalRecord
from shared.models.employment import EmploymentHistory
from shared.models.marketing import MarketingTag
from shared.models.person import Person
from shared.models.wealth import WealthAssessment

logger = logging.getLogger(__name__)


# ─── PersonSignals ─────────────────────────────────────────────────────────────


@dataclass
class PersonSignals:
    person_id: UUID
    has_vehicle: bool
    has_property: bool
    financial_distress_score: float
    gambling_score: float
    income_estimate: float | None
    net_worth_estimate: float | None
    is_employed: bool
    age: int | None
    criminal_count: int
    has_investment_signals: bool


async def assemble_person_signals(person_id: UUID, session: AsyncSession) -> PersonSignals:
    """Build a PersonSignals from DB in sequential queries (single session)."""

    person = (await session.execute(select(Person).where(Person.id == person_id))).scalars().first()

    # Employment — is_current rows
    employment = list(
        (
            await session.execute(
                select(EmploymentHistory).where(
                    EmploymentHistory.person_id == person_id,
                    EmploymentHistory.is_current == True,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )

    # Criminal records count
    criminal_count_row = (
        await session.execute(
            select(func.count(CriminalRecord.id)).where(CriminalRecord.person_id == person_id)
        )
    ).scalar()

    # Latest wealth assessment
    wealth = (
        (
            await session.execute(
                select(WealthAssessment)
                .where(WealthAssessment.person_id == person_id)
                .order_by(WealthAssessment.assessed_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    # Behavioural profile
    behavioural = (
        (
            await session.execute(
                select(BehaviouralProfile).where(BehaviouralProfile.person_id == person_id)
            )
        )
        .scalars()
        .first()
    )

    # Derived
    dob = person.date_of_birth if person else None
    age = _compute_age(dob)
    is_employed = len(employment) > 0
    financial_distress_score = behavioural.financial_distress_score if behavioural else 0.0
    gambling_score = behavioural.gambling_score if behavioural else 0.0
    income_estimate = wealth.income_estimate_usd if wealth else None
    net_worth_estimate = wealth.net_worth_estimate_usd if wealth else None
    has_vehicle = bool(wealth and wealth.vehicle_signal > 0.3)
    has_property = bool(wealth and wealth.property_signal > 0.3)
    has_investment_signals = bool(
        wealth and (wealth.crypto_signal > 0.3 or wealth.luxury_signal > 0.3)
    )

    return PersonSignals(
        person_id=person_id,
        has_vehicle=has_vehicle,
        has_property=has_property,
        financial_distress_score=financial_distress_score,
        gambling_score=gambling_score,
        income_estimate=income_estimate,
        net_worth_estimate=net_worth_estimate,
        is_employed=is_employed,
        age=age,
        criminal_count=int(criminal_count_row or 0),
        has_investment_signals=has_investment_signals,
    )


# ─── CommercialTagsEngine ──────────────────────────────────────────────────────


_COMMERCIAL_TAG_CATEGORY: dict[str, str] = {
    InsuranceTag.INSURANCE_AUTO: "InsuranceTag",
    InsuranceTag.INSURANCE_LIFE: "InsuranceTag",
    InsuranceTag.INSURANCE_HEALTH: "InsuranceTag",
    BankingTag.BANKING_BASIC: "BankingTag",
    BankingTag.BANKING_PREMIUM: "BankingTag",
    WealthTag.HIGH_NET_WORTH: "WealthTag",
    LendingTag.AUTO_LOAN_CANDIDATE: "LendingTag",
    LendingTag.PAYDAY_LOAN_CANDIDATE: "LendingTag",
    LendingTag.PERSONAL_LOAN_CANDIDATE: "LendingTag",
    LendingTag.MORTGAGE_CANDIDATE: "LendingTag",
    LendingTag.REFINANCE_CANDIDATE: "LendingTag",
    LendingTag.DEBT_CONSOLIDATION: "LendingTag",
}


class CommercialTagsEngine:
    """Run all Phase 4 commercial scorers against a PersonSignals struct."""

    def tag_person(self, signals: PersonSignals) -> list[TagResult]:
        now = datetime.now(timezone.utc)
        scoring_map: list[tuple[str, float, list[str]]] = []

        # Insurance
        s, r = _score_insurance_auto(signals.has_vehicle)
        scoring_map.append((InsuranceTag.INSURANCE_AUTO, s, r))

        s, r = _score_insurance_life(signals.age, signals.income_estimate)
        scoring_map.append((InsuranceTag.INSURANCE_LIFE, s, r))

        s, r = _score_insurance_health(signals.age, signals.is_employed)
        scoring_map.append((InsuranceTag.INSURANCE_HEALTH, s, r))

        # Banking
        s, r = _score_banking_basic(signals.is_employed, signals.age)
        scoring_map.append((BankingTag.BANKING_BASIC, s, r))

        s, r = _score_banking_premium(
            signals.income_estimate,
            signals.net_worth_estimate,
            signals.has_investment_signals,
        )
        scoring_map.append((BankingTag.BANKING_PREMIUM, s, r))

        # Wealth
        s, r = _score_high_net_worth(
            signals.net_worth_estimate,
            signals.has_property,
            signals.has_investment_signals,
        )
        scoring_map.append((WealthTag.HIGH_NET_WORTH, s, r))

        # Lending
        s, r = _score_auto_loan_candidate(
            signals.has_vehicle, signals.has_property, signals.income_estimate
        )
        scoring_map.append((LendingTag.AUTO_LOAN_CANDIDATE, s, r))

        s, r = _score_payday_loan_candidate(
            signals.financial_distress_score, signals.has_property, signals.income_estimate
        )
        scoring_map.append((LendingTag.PAYDAY_LOAN_CANDIDATE, s, r))

        s, r = _score_personal_loan_candidate(signals.is_employed, signals.financial_distress_score)
        scoring_map.append((LendingTag.PERSONAL_LOAN_CANDIDATE, s, r))

        s, r = _score_mortgage_candidate(signals.has_property, signals.income_estimate)
        scoring_map.append((LendingTag.MORTGAGE_CANDIDATE, s, r))

        s, r = _score_refinance_candidate(signals.has_property, signals.financial_distress_score)
        scoring_map.append((LendingTag.REFINANCE_CANDIDATE, s, r))

        s, r = _score_debt_consolidation(
            signals.financial_distress_score,
            signals.criminal_count,
            signals.has_vehicle,
            signals.has_property,
        )
        scoring_map.append((LendingTag.DEBT_CONSOLIDATION, s, r))

        results: list[TagResult] = []
        for tag, confidence, reasoning in scoring_map:
            threshold = _THRESHOLDS.get(tag, 0.65)
            if confidence >= threshold and reasoning:
                results.append(
                    TagResult(
                        tag=tag,
                        confidence=round(confidence, 4),
                        reasoning=reasoning,
                        scored_at=now,
                    )
                )

        return results


# ─── CommercialTaggerDaemon ────────────────────────────────────────────────────

_BATCH_SIZE = 50
_SLEEP_SECONDS = 900  # 15 minutes


class CommercialTaggerDaemon:
    """Background daemon: tags newly enriched persons with commercial signals."""

    def __init__(self) -> None:
        self._running = False
        self._last_run_at: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._engine = CommercialTagsEngine()

    def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("CommercialTaggerDaemon started")
        while self._running:
            try:
                await self._run_batch()
            except Exception:
                logger.exception("CommercialTaggerDaemon batch error")
            await asyncio.sleep(_SLEEP_SECONDS)

    async def _run_batch(self) -> None:
        cutoff = self._last_run_at
        run_started = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            persons = list(
                (
                    await session.execute(
                        select(Person)
                        .where(
                            Person.last_scraped_at.isnot(None),
                            Person.last_scraped_at > cutoff,
                        )
                        .order_by(Person.last_scraped_at.asc())
                        .limit(_BATCH_SIZE)
                    )
                )
                .scalars()
                .all()
            )

        if not persons:
            self._last_run_at = run_started
            return

        logger.info("CommercialTaggerDaemon: processing %d persons", len(persons))

        for person in persons:
            try:
                async with AsyncSessionLocal() as session:
                    signals = await assemble_person_signals(person.id, session)
                    tag_results = self._engine.tag_person(signals)
                    await _upsert_commercial_tags(person.id, tag_results, session)
                    await session.commit()
            except Exception:
                logger.exception("CommercialTaggerDaemon: failed person_id=%s", person.id)

        self._last_run_at = run_started
        logger.info("CommercialTaggerDaemon: batch complete, last_run_at=%s", self._last_run_at)


async def _upsert_commercial_tags(
    person_id: UUID,
    tag_results: list[TagResult],
    session: AsyncSession,
) -> None:
    for result in tag_results:
        existing = (
            (
                await session.execute(
                    select(MarketingTag).where(
                        MarketingTag.person_id == person_id,
                        MarketingTag.tag == result.tag,
                    )
                )
            )
            .scalars()
            .first()
        )

        category = _COMMERCIAL_TAG_CATEGORY.get(result.tag)

        if existing:
            existing.confidence = result.confidence
            existing.reasoning = result.reasoning
            existing.scored_at = result.scored_at
            existing.tag_category = category
        else:
            session.add(
                MarketingTag(
                    person_id=person_id,
                    tag=result.tag,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    scored_at=result.scored_at,
                    tag_category=category,
                )
            )
