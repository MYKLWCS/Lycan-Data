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


class MultiFieldAnomalyRequest(BaseModel):
    entities: list[dict] = Field(..., description="List of entity dicts with 'id' field")
    fields: list[str] = Field(..., min_length=1, max_length=20, description="Fields to analyze")


@router.post("/anomaly/detect")
async def detect_anomalies(req: MultiFieldAnomalyRequest):
    """Detect statistical anomalies across entity fields. No DB required — provide entities inline."""
    if len(req.entities) < 3:
        raise HTTPException(400, "At least 3 entities required for anomaly detection")
    if len(req.entities) > 10000:
        raise HTTPException(400, "Maximum 10000 entities per request")

    results = _anomaly.detect_multi_field(req.entities, req.fields)
    return {
        "anomalies": {
            field: [
                {
                    "entity_id": r.entity_id,
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
        "entities_count": len(req.entities),
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
    limit: int = Query(50, le=200),
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
    limit: int = Query(50, le=200),
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
    limit: int = Query(50, le=200),
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
    limit: int = Query(50, le=200),
    session: AsyncSession = DbDep,
):
    """Find persons with unusually high connection counts (network hubs / fraud ring centers)."""
    try:
        data = await _temporal.find_network_anomalies(session, min_connections, limit)
    except Exception as exc:
        logger.exception("network_anomalies failed")
        raise HTTPException(500, "Internal error") from exc

    return {"network_hubs": _serialize(data), "count": len(data)}
