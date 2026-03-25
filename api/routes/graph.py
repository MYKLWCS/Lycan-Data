"""Graph intelligence API routes — company search, entity networks, fraud rings."""

import logging
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _serialize
from modules.graph.company_intel import CompanyIntelligenceEngine
from modules.graph.entity_graph import EntityGraphBuilder
from modules.graph.ubo_discovery import UBODiscoveryEngine
from shared.models.employment import EmploymentHistory
from shared.models.person import Person

router = APIRouter()
logger = logging.getLogger(__name__)

_company_engine = CompanyIntelligenceEngine()
_graph_builder = EntityGraphBuilder()
_ubo_engine = UBODiscoveryEngine()


# ── Request schemas ───────────────────────────────────────────────────────────


class FraudRingsRequest(BaseModel):
    min_connections: int = Field(default=3, ge=1, le=50)


class SharedConnectionsRequest(BaseModel):
    person_ids: list[str]


class CompanyIntelRequest(BaseModel):
    company_name: str
    jurisdiction: str | None = Field(default=None)
    depth: int = Field(default=2, ge=1, le=5)


class UBORequest(BaseModel):
    company_name: str
    jurisdiction: str | None = Field(default=None)
    max_depth: int = Field(default=5, ge=1, le=10)


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

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    return {
        "person_id": person_id,
        "depth": depth,
        "nodes": _serialize(nodes),
        "edges": _serialize(edges),
        "node_count": len(nodes),
        "edge_count": len(edges),
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


@router.get("/nodes")
async def graph_nodes(
    limit: int = Query(500, ge=1, le=500, description="Max nodes per page"),
    offset: int = Query(0, ge=0),
    entity_types: str | None = Query(
        None, description="Comma-separated entity types: person,company,address,phone,email"
    ),
    session: AsyncSession = DbDep,
):
    """Paginated list of graph nodes, ordered by degree (risk_score desc for persons)."""
    types = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        nodes = await _graph_builder.get_nodes_paginated(
            session, limit=limit, offset=offset, entity_types=types
        )
    except Exception as exc:
        logger.exception("graph_nodes failed")
        raise HTTPException(500, "Internal error") from exc
    return {"nodes": _serialize(nodes), "count": len(nodes), "offset": offset}


@router.get("/edges")
async def graph_edges(
    limit: int = Query(1000, ge=1, le=2000, description="Max edges per page"),
    offset: int = Query(0, ge=0),
    session: AsyncSession = DbDep,
):
    """Paginated list of relationship edges."""
    try:
        edges = await _graph_builder.get_edges_paginated(session, limit=limit, offset=offset)
    except Exception as exc:
        logger.exception("graph_edges failed")
        raise HTTPException(500, "Internal error") from exc
    return {"edges": _serialize(edges), "count": len(edges), "offset": offset}


@router.get("/path")
async def graph_path(
    from_id: str = Query(..., alias="from", description="Source node ID"),
    to_id: str = Query(..., alias="to", description="Target node ID"),
    entity_types: str | None = Query(
        None, description="Comma-separated traversal filter: person,company"
    ),
    max_hops: int = Query(6, ge=1, description="Maximum hops; hard cap is 10"),
    session: AsyncSession = DbDep,
):
    """BFS shortest path between two nodes with optional entity_type traversal filter."""
    if max_hops > 10:
        raise HTTPException(400, "max_hops must be <= 10")
    types = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        result = await _graph_builder.find_shortest_path(
            from_id, to_id, session, entity_types=types, max_hops=max_hops
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("graph_path failed from=%s to=%s", from_id, to_id)
        raise HTTPException(500, "Internal error") from exc
    return result


@router.get("/entity/{entity_type}/{entity_id}/expand")
async def graph_expand(
    entity_type: str,
    entity_id: str,
    session: AsyncSession = DbDep,
):
    """Return 1-hop expansion for any entity node."""
    try:
        result = await _graph_builder.expand_entity(entity_type, entity_id, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("graph_expand failed type=%s id=%s", entity_type, entity_id)
        raise HTTPException(500, "Internal error") from exc
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "nodes": _serialize(result.get("nodes", [])),
        "edges": _serialize(result.get("edges", [])),
    }


@router.post("/company/intel")
async def company_intel(req: CompanyIntelRequest, session: AsyncSession = DbDep):
    """Crawl all registered company data sources and return merged officer/metadata."""
    try:
        crawled = await _ubo_engine.crawl_company(req.company_name, req.jurisdiction)
    except Exception as exc:
        logger.exception("company_intel failed name=%s", req.company_name)
        raise HTTPException(500, "Internal error") from exc

    return {
        "company_name": crawled.company_name,
        "jurisdiction": crawled.jurisdiction,
        "status": crawled.status,
        "incorporation_date": crawled.incorporation_date,
        "entity_type": crawled.entity_type,
        "lei": crawled.lei,
        "company_numbers": crawled.company_numbers,
        "registered_addresses": crawled.registered_addresses,
        "officers": [
            {
                "name": o.name,
                "position": o.position,
                "source": o.source,
                "jurisdiction": o.jurisdiction,
                "start_date": o.start_date,
                "end_date": o.end_date,
                "confidence": o.confidence,
            }
            for o in crawled.officers
        ],
        "sec_filings": crawled.sec_filings,
        "has_proxy_filing": crawled.has_proxy_filing,
        "data_sources": crawled.data_sources,
        "crawl_errors": crawled.crawl_errors,
    }


@router.post("/company/ubo")
async def company_ubo(req: UBORequest, session: AsyncSession = DbDep):
    """Run recursive BFS UBO chain discovery for a company."""
    try:
        result = await _ubo_engine.discover(
            req.company_name, req.jurisdiction, req.max_depth, session
        )
    except Exception as exc:
        logger.exception("company_ubo failed name=%s", req.company_name)
        raise HTTPException(500, "Internal error") from exc

    return {
        "root_company": result.root_company,
        "jurisdiction": result.jurisdiction,
        "max_depth_used": result.max_depth_used,
        "partial": result.partial,
        "discovered_at": result.discovered_at.isoformat(),
        "nodes": result.nodes,
        "edges": result.edges,
        "ubo_candidates": [
            {
                "name": c.name,
                "person_id": c.person_id,
                "chain": c.chain,
                "depth": c.depth,
                "controlling_roles": c.controlling_roles,
                "jurisdictions": c.jurisdictions,
                "confidence": c.confidence,
                "is_natural_person": c.is_natural_person,
                "sanctions_hits": c.sanctions_hits,
                "risk_score": c.risk_score,
            }
            for c in result.ubo_candidates
        ],
        "risk_flags": result.risk_flags,
        "crawl_errors": result.crawl_errors,
    }


@router.get("/company/{company_id}/persons")
async def company_persons(company_id: str, session: AsyncSession = DbDep):
    """Return all persons linked to a company via EmploymentHistory.

    ``company_id`` is treated as a UUID first; if that fails it is used as a
    company name substring search against EmploymentHistory.employer_name.
    """
    try:
        # Try UUID lookup first (employment record FK doesn't exist but person
        # lookup by their linked company does via EmploymentHistory)
        try:
            _uuid.UUID(company_id)
            # If it parses as UUID treat it as a company lookup by exact name —
            # there is no Company table in this schema, so fall through to name
            # substring search
            is_uuid = True
        except ValueError:
            is_uuid = False

        stmt = (
            select(Person)
            .join(EmploymentHistory, EmploymentHistory.person_id == Person.id)
            .where(
                EmploymentHistory.employer_name.ilike(f"%{company_id}%")
                if not is_uuid
                else EmploymentHistory.employer_name.ilike(f"%{company_id}%")
            )
            .distinct()
        )
        result = await session.execute(stmt)
        persons = result.scalars().all()
    except Exception as exc:
        logger.exception("company_persons failed id=%s", company_id)
        raise HTTPException(500, "Internal error") from exc

    return {
        "company_id": company_id,
        "persons": _serialize(persons),
        "count": len(persons),
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
