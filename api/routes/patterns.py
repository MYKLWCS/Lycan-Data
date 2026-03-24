"""Pattern detection API routes."""
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _serialize
from modules.patterns.anomaly import StatisticalAnomalyDetector
from modules.patterns.temporal import TemporalPatternAnalyzer

router = APIRouter()
logger = logging.getLogger(__name__)

_temporal = TemporalPatternAnalyzer()
_anomaly = StatisticalAnomalyDetector()


class AnomalyDetectRequest(BaseModel):
    person_ids: list[uuid.UUID] | None = Field(None, description="Specific person IDs to analyze. If omitted, uses all persons.")
    fields: list[str] = Field(
        default=["default_risk_score", "source_reliability", "darkweb_exposure", "behavioural_risk"],
        description="Person fields to analyze for anomalies",
    )
    min_score: float = Field(0.0, ge=0.0, le=1.0)
    limit: int = Field(200, ge=3, le=5000)


@router.post("/anomaly/detect")
async def detect_anomalies(req: AnomalyDetectRequest, session: AsyncSession = DbDep):
    """Detect statistical anomalies across persons. Loads data from DB automatically."""
    from sqlalchemy import select
    from shared.models.person import Person

    q = select(Person).limit(req.limit)
    if req.person_ids:
        q = q.where(Person.id.in_(req.person_ids))
    persons = (await session.scalars(q)).all()

    if len(persons) < 3:
        return {"anomalies": {}, "fields_analyzed": req.fields, "entities_count": len(persons),
                "message": "Need at least 3 persons in DB to detect anomalies"}

    entities = [
        {
            "id": str(p.id),
            "full_name": p.full_name,
            "default_risk_score": p.default_risk_score or 0.0,
            "source_reliability": p.source_reliability or 0.5,
            "darkweb_exposure": p.darkweb_exposure or 0.0,
            "behavioural_risk": p.behavioural_risk or 0.0,
            "relationship_score": p.relationship_score or 0.0,
        }
        for p in persons
    ]

    results = _anomaly.detect_multi_field(entities, req.fields)
    return {
        "anomalies": {
            field: [
                {
                    "entity_id": r.entity_id,
                    "full_name": next((e["full_name"] for e in entities if e["id"] == r.entity_id), None),
                    "value": r.value,
                    "z_score": r.z_score,
                    "severity": r.severity,
                    "reason": r.reason,
                }
                for r in field_results
            ]
            for field, field_results in results.items()
        },
        "fields_analyzed": req.fields,
        "entities_count": len(entities),
    }


@router.get("/temporal/change-velocity/{person_id}")
async def change_velocity(
    person_id: str,
    window_days: int = Query(30, ge=1, le=365),
    session: AsyncSession = DbDep,
):
    """Detect how fast a person's records are changing (activity velocity)."""
    try:
        uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {person_id!r}")

    try:
        data = await _temporal.detect_change_velocity(person_id, session, window_days)
    except Exception as exc:
        logger.exception("change_velocity failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return {"person_id": person_id, "window_days": window_days, "velocity": _serialize(data)}


@router.get("/temporal/address-patterns")
async def address_patterns(
    min_changes: int = Query(3, ge=2, le=50),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = DbDep,
):
    """Find persons with high address change frequency (relocation anomaly)."""
    try:
        data = await _temporal.find_address_change_patterns(session, min_changes, limit)
    except Exception as exc:
        logger.exception("address_patterns failed")
        raise HTTPException(500, "Internal error") from exc

    return {"patterns": _serialize(data), "count": len(data)}


@router.get("/temporal/identifier-churn")
async def identifier_churn(
    min_changes: int = Query(3, ge=2, le=20),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = DbDep,
):
    """Find persons with many phone/email changes (burner indicator)."""
    try:
        data = await _temporal.find_identifier_change_patterns(session, min_changes, limit)
    except Exception as exc:
        logger.exception("identifier_churn failed")
        raise HTTPException(500, "Internal error") from exc

    return {"patterns": _serialize(data), "count": len(data)}


@router.get("/risk/co-occurring-flags")
async def co_occurring_flags(
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = DbDep,
):
    """Find persons appearing in multiple risk tables simultaneously."""
    try:
        data = await _temporal.find_co_occurring_risk_flags(session, limit)
    except Exception as exc:
        logger.exception("co_occurring_flags failed")
        raise HTTPException(500, "Internal error") from exc

    return {"high_risk_persons": _serialize(data), "count": len(data)}


@router.get("/risk/network-anomalies")
async def network_anomalies(
    min_connections: int = Query(10, ge=3, le=500),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = DbDep,
):
    """Find persons with unusually high connection counts (network hubs / fraud ring centers)."""
    try:
        data = await _temporal.find_network_anomalies(session, min_connections, limit)
    except Exception as exc:
        logger.exception("network_anomalies failed")
        raise HTTPException(500, "Internal error") from exc

    return {"network_hubs": _serialize(data), "count": len(data)}
