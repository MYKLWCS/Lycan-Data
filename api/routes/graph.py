"""Graph intelligence API routes — company search, entity networks, fraud rings."""
import dataclasses
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from modules.graph.company_intel import CompanyIntelligenceEngine
from modules.graph.entity_graph import EntityGraphBuilder

router = APIRouter()
logger = logging.getLogger(__name__)

_company_engine = CompanyIntelligenceEngine()
_graph_builder = EntityGraphBuilder()


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _serialize(obj):
    """Recursively make dicts/lists/datetimes JSON-safe."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _serialize(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    return obj


# ── Request schemas ───────────────────────────────────────────────────────────

class FraudRingsRequest(BaseModel):
    min_connections: int = Field(default=3, ge=1, le=50)


class SharedConnectionsRequest(BaseModel):
    person_ids: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/company/search")
async def search_company(
    name: str = Query(..., description="Company name to search"),
    state: str | None = Query(None, description="Optional state filter"),
    session: AsyncSession = DbDep,
):
    """Search for companies by name, optionally filtered by state."""
    companies = await _company_engine.search_company(name, state, session)
    return {
        "companies": [_serialize(c) for c in companies],
        "count": len(companies),
    }


@router.get("/company/network")
async def company_network(
    name: str = Query(..., description="Company name"),
    session: AsyncSession = DbDep,
):
    """Return a node/edge network graph for a company."""
    network = await _company_engine.get_company_network(name, session)
    return {
        "nodes": _serialize(network.get("nodes", [])),
        "edges": _serialize(network.get("edges", [])),
        "company_name": name,
    }


@router.get("/person/{person_id}/network")
async def person_network(
    person_id: str,
    depth: int = Query(2, ge=1, le=3, description="Graph traversal depth (max 3)"),
    session: AsyncSession = DbDep,
):
    """Build a relationship graph centred on a person up to the given depth."""
    try:
        graph = await _graph_builder.build_person_graph(person_id, session, depth=depth)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Graph build failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return {
        "person_id": person_id,
        "depth": depth,
        "nodes": _serialize(graph.get("nodes", [])),
        "edges": _serialize(graph.get("edges", [])),
    }


@router.get("/person/{person_id}/companies")
async def person_companies(person_id: str, session: AsyncSession = DbDep):
    """Return all companies associated with a person."""
    try:
        companies = await _company_engine.get_person_companies(person_id, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Company lookup failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return {
        "person_id": person_id,
        "companies": _serialize(companies),
    }


@router.post("/fraud-rings")
async def detect_fraud_rings(req: FraudRingsRequest, session: AsyncSession = DbDep):
    """Detect clusters of persons sharing addresses or phone numbers."""
    try:
        rings = await _graph_builder.detect_fraud_rings(
            session, min_connections=req.min_connections
        )
    except Exception as exc:
        logger.exception("Fraud ring detection failed")
        raise HTTPException(500, "Internal error") from exc

    return {
        "rings": _serialize(rings),
        "count": len(rings),
    }


@router.post("/shared-connections")
async def shared_connections(req: SharedConnectionsRequest, session: AsyncSession = DbDep):
    """Find shared identifiers, addresses, and employers across a list of persons."""
    if len(req.person_ids) < 2:
        raise HTTPException(400, "At least 2 person_ids are required")

    try:
        connections = await _graph_builder.find_shared_connections(req.person_ids, session)
    except Exception as exc:
        logger.exception("Shared connection lookup failed")
        raise HTTPException(500, "Internal error") from exc

    return {
        "connections": _serialize(connections),
        "count": len(connections),
    }
