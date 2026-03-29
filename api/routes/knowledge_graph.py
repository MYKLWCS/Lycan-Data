"""Knowledge Graph API routes — AGE-backed OSINT graph + saturation crawling."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _serialize
from modules.graph.knowledge_graph import EDGE_LABELS, VERTEX_LABELS, KnowledgeGraphBuilder
from modules.graph.saturation_crawler import GrowthControls, SaturationCrawler

router = APIRouter()
logger = logging.getLogger(__name__)

_graph = KnowledgeGraphBuilder()


# ── Request schemas ───────────────────────────────────────────────────────────


class AddEntityRequest(BaseModel):
    label: str = Field(..., description="Node label: Person, Company, Address, etc.")
    entity_id: str | None = Field(None, description="Explicit ID; auto-generated if omitted.")
    properties: dict = Field(default_factory=dict)


class AddRelationshipRequest(BaseModel):
    from_label: str
    from_id: str
    rel_type: str = Field(..., description="Edge label: OFFICER_OF, OWNS, LIVES_AT, etc.")
    to_label: str
    to_id: str
    properties: dict = Field(default_factory=dict)


class SaturationRequest(BaseModel):
    seed: str = Field(..., description="Seed entity identifier (name, company name, etc.)")
    seed_type: str = Field("person", description="person or company")
    max_depth: int = Field(3, ge=1, le=6)
    max_entities: int = Field(200, ge=10, le=1000)
    confidence_threshold: float = Field(0.6, ge=0.0, le=1.0)
    novelty_threshold: float = Field(0.05, ge=0.01, le=0.5)
    relationship_filter: list[str] | None = Field(
        None, description="Only follow these edge types. Null = follow all."
    )


class SearchEntitiesRequest(BaseModel):
    label: str
    search_term: str
    limit: int = Field(20, ge=1, le=100)


class PatternDetectRequest(BaseModel):
    pattern_type: str = Field(
        ...,
        description="One of: circular_ownership, shell_company, shared_officers, co_located_companies",
    )


# ── Entity CRUD ───────────────────────────────────────────────────────────────


@router.post("/entity")
async def add_entity(req: AddEntityRequest, session: AsyncSession = DbDep):
    """Add or merge a vertex in the OSINT knowledge graph."""
    if req.label not in VERTEX_LABELS:
        raise HTTPException(400, f"Invalid label. Must be one of: {sorted(VERTEX_LABELS)}")
    try:
        eid = await _graph.add_entity(req.label, req.entity_id or "", req.properties, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("add_entity failed")
        raise HTTPException(500, "Internal error") from exc
    return {"entity_id": eid, "label": req.label}


@router.get("/entity/{label}/{entity_id}")
async def get_entity(label: str, entity_id: str, session: AsyncSession = DbDep):
    """Fetch a single vertex by label and entity_id."""
    if label not in VERTEX_LABELS:
        raise HTTPException(400, f"Invalid label: {label}")
    entity = await _graph.get_entity(label, entity_id, session)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    return {"entity": _serialize(entity), "label": label}


@router.delete("/entity/{label}/{entity_id}")
async def delete_entity(label: str, entity_id: str, session: AsyncSession = DbDep):
    """Delete a vertex and all its edges."""
    if label not in VERTEX_LABELS:
        raise HTTPException(400, f"Invalid label: {label}")
    await _graph.delete_entity(label, entity_id, session)
    return {"deleted": True, "entity_id": entity_id}


# ── Relationship CRUD ─────────────────────────────────────────────────────────


@router.post("/relationship")
async def add_relationship(req: AddRelationshipRequest, session: AsyncSession = DbDep):
    """Add or merge an edge between two vertices."""
    if req.from_label not in VERTEX_LABELS:
        raise HTTPException(400, f"Invalid from_label: {req.from_label}")
    if req.to_label not in VERTEX_LABELS:
        raise HTTPException(400, f"Invalid to_label: {req.to_label}")
    if req.rel_type not in EDGE_LABELS:
        raise HTTPException(400, f"Invalid rel_type. Must be one of: {sorted(EDGE_LABELS)}")
    try:
        await _graph.add_relationship(
            req.from_label, req.from_id,
            req.rel_type,
            req.to_label, req.to_id,
            properties=req.properties,
            session=session,
        )
    except Exception as exc:
        logger.exception("add_relationship failed")
        raise HTTPException(500, "Internal error") from exc
    return {"created": True, "rel_type": req.rel_type}


@router.delete("/relationship")
async def remove_relationship(req: AddRelationshipRequest, session: AsyncSession = DbDep):
    """Delete a specific edge between two vertices."""
    try:
        await _graph.remove_relationship(
            req.from_label, req.from_id,
            req.rel_type,
            req.to_label, req.to_id,
            session=session,
        )
    except Exception as exc:
        logger.exception("remove_relationship failed")
        raise HTTPException(500, "Internal error") from exc
    return {"deleted": True}


# ── Graph queries ─────────────────────────────────────────────────────────────


@router.get("/connections/{entity_id}")
async def find_connections(
    entity_id: str,
    max_depth: int = Query(3, ge=1, le=6),
    session: AsyncSession = DbDep,
):
    """Find all entities connected to the given entity within N hops."""
    try:
        result = await _graph.find_connections(entity_id, max_depth, session)
    except Exception as exc:
        logger.warning("find_connections failed id=%s: %s", entity_id, exc)
        result = {"nodes": [], "edges": []}
    return {
        "entity_id": entity_id,
        "max_depth": max_depth,
        "nodes": _serialize(result.get("nodes", [])),
        "edges": _serialize(result.get("edges", [])),
        "node_count": len(result.get("nodes", [])),
    }


@router.get("/company-graph/{company_id}")
async def build_company_graph(
    company_id: str,
    max_depth: int = Query(3, ge=1, le=5),
    session: AsyncSession = DbDep,
):
    """Build full network graph for a company from the knowledge graph."""
    try:
        result = await _graph.build_company_graph(company_id, max_depth, session)
    except Exception as exc:
        logger.warning("build_company_graph failed id=%s: %s", company_id, exc)
        result = {"nodes": [], "edges": []}
    return _serialize(result)


@router.get("/expand/{entity_id}")
async def expand_node(entity_id: str, session: AsyncSession = DbDep):
    """
    1-hop expansion from a node. Used by the expanding search UI
    when a user clicks a node to see its immediate neighbours.
    """
    try:
        result = await _graph.expand_node(entity_id, session)
    except Exception as exc:
        logger.warning("expand_node failed id=%s: %s", entity_id, exc)
        result = {"centre": None, "neighbours": []}
    return {
        "entity_id": entity_id,
        "centre": _serialize(result.get("centre")),
        "neighbours": _serialize(result.get("neighbours", [])),
        "neighbour_count": len(result.get("neighbours", [])),
    }


@router.post("/search")
async def search_entities(req: SearchEntitiesRequest, session: AsyncSession = DbDep):
    """Search graph entities by label and name substring."""
    if req.label not in VERTEX_LABELS:
        raise HTTPException(400, f"Invalid label: {req.label}")
    try:
        results = await _graph.search_entities(req.label, req.search_term, req.limit, session)
    except Exception as exc:
        logger.exception("search_entities failed")
        raise HTTPException(500, "Internal error") from exc
    return {"results": _serialize(results), "count": len(results)}


@router.post("/patterns")
async def detect_patterns(req: PatternDetectRequest, session: AsyncSession = DbDep):
    """Run pattern detection queries on the knowledge graph."""
    try:
        results = await _graph.detect_patterns(req.pattern_type, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("detect_patterns failed type=%s", req.pattern_type)
        raise HTTPException(500, "Internal error") from exc
    return {"pattern_type": req.pattern_type, "results": _serialize(results), "count": len(results)}


@router.get("/stats")
async def graph_stats(session: AsyncSession = DbDep):
    """Return vertex/edge counts per label."""
    try:
        stats = await _graph.graph_stats(session)
    except Exception as exc:
        logger.exception("graph_stats failed")
        raise HTTPException(500, "Internal error") from exc
    return _serialize(stats)


# ── Saturation Crawl ──────────────────────────────────────────────────────────


@router.post("/saturate")
async def saturate_crawl(req: SaturationRequest, session: AsyncSession = DbDep):
    """
    Run a saturation crawl starting from a seed entity.

    Discovers connected entities across all registered crawlers,
    queues them for further crawling, and stops when data novelty
    drops below the threshold (default 5%).

    Returns statistics and whether saturation was reached.
    """
    if req.seed_type not in ("person", "company"):
        raise HTTPException(400, "seed_type must be 'person' or 'company'")

    controls = GrowthControls(
        max_depth=req.max_depth,
        max_entities=req.max_entities,
        confidence_threshold=req.confidence_threshold,
        novelty_threshold=req.novelty_threshold,
        relationship_filter=set(req.relationship_filter) if req.relationship_filter else None,
    )

    crawler = SaturationCrawler(_graph, controls)

    try:
        result = await crawler.saturate(req.seed, req.seed_type, session)
    except Exception as exc:
        logger.exception("saturate_crawl failed seed=%s", req.seed)
        raise HTTPException(500, "Internal error") from exc

    return _serialize(result)


# ── Schema metadata ───────────────────────────────────────────────────────────


@router.get("/schema")
async def graph_schema():
    """Return the knowledge graph schema: available vertex and edge labels."""
    return {
        "vertex_labels": sorted(VERTEX_LABELS),
        "edge_labels": sorted(EDGE_LABELS),
    }
