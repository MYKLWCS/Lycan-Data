"""Watchlist match endpoints."""

import logging
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.models.watchlist import WatchlistMatch

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{person_id}")
async def get_watchlist_matches(
    person_id: uuid.UUID, db: AsyncSession = DbDep, confirmed_only: bool = False
):
    q = select(WatchlistMatch).where(WatchlistMatch.person_id == person_id)
    if confirmed_only:
        q = q.where(WatchlistMatch.is_confirmed)
    rows = (await db.scalars(q)).all()
    return {
        "matches": [
            {
                "id": str(r.id),
                "list_name": r.list_name,
                "list_type": r.list_type,
                "match_score": r.match_score,
                "match_name": r.match_name,
                "listed_date": r.listed_date,
                "reason": r.reason,
                "source_url": r.source_url,
                "is_confirmed": r.is_confirmed,
                "meta": r.meta,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/{match_id}/confirm")
async def confirm_match(match_id: uuid.UUID, db: AsyncSession = DbDep):
    row = await db.get(WatchlistMatch, match_id)
    if not row:
        raise HTTPException(status_code=404, detail="Match not found")
    row.is_confirmed = True
    await db.commit()
    return {"message": "Match confirmed", "id": str(match_id)}
