"""Financial & AML API routes."""

import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _model_to_dict
from modules.enrichers.financial_aml import FinancialIntelligenceEngine
from modules.enrichers.marketing_tags import HighInterestBorrowerScorer
from shared.models.address import Address
from shared.models.credit_risk import CreditRiskAssessment
from shared.models.criminal import CriminalRecord
from shared.models.employment import EmploymentHistory
from shared.models.watchlist import WatchlistMatch
from shared.models.wealth import WealthAssessment

router = APIRouter()
logger = logging.getLogger(__name__)

_engine = FinancialIntelligenceEngine()
_borrower_scorer = HighInterestBorrowerScorer()


# ── Request schemas ───────────────────────────────────────────────────────────


class BorrowerScoreRequest(BaseModel):
    person_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/{person_id}/score")
async def score_person(person_id: str, session: AsyncSession = DbDep):
    """Run FinancialIntelligenceEngine on the person and return FinancialProfile."""
    try:
        profile = await _engine.score_person(person_id, session)
    except Exception as exc:
        logger.exception("Scoring failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    credit = profile.credit
    aml = profile.aml
    fraud = profile.fraud

    return {
        "person_id": profile.person_id,
        "credit_score": credit.score,
        "credit_tier": credit.risk_category,
        "aml_risk_score": aml.risk_score,
        "is_pep": aml.is_pep,
        "fraud_score": fraud.fraud_score,
        "fraud_tier": fraud.tier,
        "darkweb_mention_count": aml.darkweb_mention_count,
        "component_breakdown": credit.component_breakdown,
        "fraud_indicators": fraud.fraud_indicators,
        "assessed_at": profile.assessed_at.isoformat(),
    }


@router.get("/{person_id}")
async def get_latest_assessment(person_id: str, session: AsyncSession = DbDep):
    """Return the latest CreditRiskAssessment from DB for the person."""
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {person_id!r}")

    row = (
        (
            await session.execute(
                select(CreditRiskAssessment)
                .where(CreditRiskAssessment.person_id == uid)
                .order_by(CreditRiskAssessment.assessed_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    if not row:
        raise HTTPException(404, "No credit risk assessment found for this person")

    return _model_to_dict(row)


@router.get("/{person_id}/aml")
async def get_aml_matches(person_id: str):
    """Redirect to /watchlist/{person_id} — canonical AML match endpoint."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/watchlist/{person_id}", status_code=307)


@router.post("/borrower-score")
async def borrower_score(req: BorrowerScoreRequest, session: AsyncSession = DbDep):
    """Score a person as a high-interest borrower candidate."""
    try:
        uid = uuid.UUID(req.person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {req.person_id!r}")

    criminals = list(
        (await session.execute(select(CriminalRecord).where(CriminalRecord.person_id == uid)))
        .scalars()
        .all()
    )

    addresses = list(
        (await session.execute(select(Address).where(Address.person_id == uid))).scalars().all()
    )

    employment = list(
        (await session.execute(select(EmploymentHistory).where(EmploymentHistory.person_id == uid)))
        .scalars()
        .all()
    )

    wealth = (
        (
            await session.execute(
                select(WealthAssessment)
                .where(WealthAssessment.person_id == uid)
                .order_by(WealthAssessment.assessed_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    profile = _borrower_scorer.score(criminals, addresses, employment, wealth)

    return {
        "person_id": req.person_id,
        "borrower_score": profile.score,
        "tier": profile.tier,
        "applicable_products": profile.applicable_products,
        "signals": profile.signals,
    }
