"""Behavioural profile endpoints."""
import uuid
import logging
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import DbDep
from shared.models.behavioural import BehaviouralProfile, BehaviouralSignal

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/{person_id}")
async def get_behavioural_profile(person_id: uuid.UUID, db: AsyncSession = DbDep):
    row = await db.scalar(select(BehaviouralProfile).where(BehaviouralProfile.person_id == person_id))
    if not row:
        raise HTTPException(status_code=404, detail="No behavioural profile found")
    signals = (await db.scalars(select(BehaviouralSignal).where(BehaviouralSignal.profile_id == row.id))).all()
    return {
        "profile": {
            "id": str(row.id), "person_id": str(row.person_id),
            "gambling_score": row.gambling_score, "drug_signal_score": row.drug_signal_score,
            "fraud_score": row.fraud_score, "violence_score": row.violence_score,
            "financial_distress_score": row.financial_distress_score,
            "criminal_signal_score": row.criminal_signal_score,
            "active_hours": row.active_hours, "top_locations": row.top_locations,
            "interests": row.interests, "languages_used": row.languages_used,
            "sentiment_avg": row.sentiment_avg, "last_assessed_at": row.last_assessed_at,
            "meta": row.meta,
        },
        "signals": [{"id": str(s.id), "signal_type": s.signal_type, "score": s.score,
                     "evidence_text": s.evidence_text, "source_url": s.source_url,
                     "source_platform": s.source_platform} for s in signals],
    }
