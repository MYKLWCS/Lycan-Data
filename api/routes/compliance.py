"""GDPR opt-out / compliance endpoints."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.models.opt_out import OptOut

router = APIRouter()
logger = logging.getLogger(__name__)


class OptOutRequest(BaseModel):
    person_id: uuid.UUID | None = None
    email: str | None = None
    request_type: str = "erasure"  # erasure, access, portability, objection


@router.post("/opt-out")
async def submit_opt_out(req: OptOutRequest, db: AsyncSession = DbDep):
    if not req.person_id and not req.email:
        raise HTTPException(status_code=422, detail="person_id or email required")
    record = OptOut(person_id=req.person_id, email=req.email, request_type=req.request_type)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": str(record.id), "status": record.status, "request_type": record.request_type}


@router.get("/opt-outs")
async def list_opt_outs(db: AsyncSession = DbDep, status: str | None = None):
    q = select(OptOut).order_by(OptOut.created_at.desc())
    if status:
        q = q.where(OptOut.status == status)
    rows = (await db.scalars(q)).all()
    return {
        "opt_outs": [
            {
                "id": str(r.id),
                "person_id": str(r.person_id) if r.person_id else None,
                "email": r.email,
                "request_type": r.request_type,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/opt-outs/{opt_out_id}/process")
async def process_opt_out(opt_out_id: uuid.UUID, db: AsyncSession = DbDep):
    row = await db.get(OptOut, opt_out_id)
    if not row:
        raise HTTPException(status_code=404, detail="Opt-out not found")
    row.status = "processed"
    row.processed_at = datetime.now(UTC)
    await db.commit()
    return {"message": "Opt-out processed", "id": str(opt_out_id)}
