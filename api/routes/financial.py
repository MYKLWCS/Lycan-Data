"""Financial & AML API routes."""
import dataclasses
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from modules.enrichers.financial_aml import FinancialIntelligenceEngine
from modules.enrichers.marketing_tags import HighInterestBorrowerScorer
from shared.models.address import Address
from shared.models.criminal import CriminalRecord
from shared.models.credit_risk import CreditRiskAssessment
from shared.models.employment import EmploymentHistory
from shared.models.watchlist import WatchlistMatch
from shared.models.wealth import WealthAssessment

router = APIRouter()

_engine = FinancialIntelligenceEngine()
_borrower_scorer = HighInterestBorrowerScorer()


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _model_to_dict(obj) -> dict:
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if val is None:
            out[col.name] = None
        elif hasattr(val, "isoformat"):
            out[col.name] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            out[col.name] = str(val)
        else:
            out[col.name] = val
    return out


def _safe_asdict(dc) -> dict:
    """Convert a dataclass to dict, serialising datetime fields."""
    raw = dataclasses.asdict(dc)
    return _serialize_datetimes(raw)


def _serialize_datetimes(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_datetimes(i) for i in obj]
    return obj


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
        raise HTTPException(500, f"Scoring failed: {exc}") from exc

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

    row = (await session.execute(
        select(CreditRiskAssessment)
        .where(CreditRiskAssessment.person_id == uid)
        .order_by(CreditRiskAssessment.assessed_at.desc())
        .limit(1)
    )).scalars().first()

    if not row:
        raise HTTPException(404, "No credit risk assessment found for this person")

    return _model_to_dict(row)


@router.get("/{person_id}/aml")
async def get_aml_matches(person_id: str, session: AsyncSession = DbDep):
    """Return all WatchlistMatch rows for the person."""
    try:
        uid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {person_id!r}")

    rows = (await session.execute(
        select(WatchlistMatch).where(WatchlistMatch.person_id == uid)
    )).scalars().all()

    return {
        "person_id": person_id,
        "matches": [
            {
                "id": str(r.id),
                "list_name": r.list_name,
                "list_type": r.list_type,
                "match_score": r.match_score,
                "is_confirmed": r.is_confirmed,
                "matched_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/borrower-score")
async def borrower_score(req: BorrowerScoreRequest, session: AsyncSession = DbDep):
    """Score a person as a high-interest borrower candidate."""
    try:
        uid = uuid.UUID(req.person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {req.person_id!r}")

    criminals = list((await session.execute(
        select(CriminalRecord).where(CriminalRecord.person_id == uid)
    )).scalars().all())

    addresses = list((await session.execute(
        select(Address).where(Address.person_id == uid)
    )).scalars().all())

    employment = list((await session.execute(
        select(EmploymentHistory).where(EmploymentHistory.person_id == uid)
    )).scalars().all())

    wealth = (await session.execute(
        select(WealthAssessment)
        .where(WealthAssessment.person_id == uid)
        .order_by(WealthAssessment.assessed_at.desc())
        .limit(1)
    )).scalars().first()

    profile = _borrower_scorer.score(criminals, addresses, employment, wealth)

    return {
        "person_id": req.person_id,
        "borrower_score": profile.score,
        "tier": profile.tier,
        "applicable_products": profile.applicable_products,
        "signals": profile.signals,
    }
