"""Alert endpoints."""
import uuid
import logging
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, update
from api.deps import DbDep
from shared.models.alert import Alert

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/")
async def list_alerts(db: DbDep, unread_only: bool = False, limit: int = Query(50, ge=1, le=500)):
    q = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if unread_only:
        q = q.where(Alert.is_read == False)
    rows = (await db.scalars(q)).all()
    return {"alerts": [{"id": str(r.id), "alert_type": r.alert_type, "severity": r.severity,
                         "title": r.title, "body": r.body, "is_read": r.is_read,
                         "person_id": str(r.person_id) if r.person_id else None,
                         "created_at": r.created_at} for r in rows],
            "count": len(rows)}

@router.post("/{alert_id}/read")
async def mark_read(alert_id: uuid.UUID, db: DbDep):
    row = await db.get(Alert, alert_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.is_read = True
    await db.commit()
    return {"message": "Marked as read"}

@router.post("/mark-all-read")
async def mark_all_read(db: DbDep):
    await db.execute(update(Alert).where(Alert.is_read == False).values(is_read=True))
    await db.commit()
    return {"message": "All alerts marked as read"}
