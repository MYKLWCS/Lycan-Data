"""Relationship Expansion API routes — family trees, networks, scoring."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from modules.graph.relationship_expansion import relationship_engine
from shared.events import event_bus

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemas ────────────────────────────────────────────────────────


class AddRelationshipRequest(BaseModel):
    person_a_id: str
    person_b_id: str
    relationship_type: str  # Raw label like "spouse", "parent", "co-worker"
    source: str = "manual"
    evidence: dict | None = None


class ExpandRelationshipsRequest(BaseModel):
    depth: int = Field(default=2, ge=1, le=4)


# ── Person relationship endpoints ─────────────────────────────────────────


@router.get("/persons/{person_id}/relationships")
async def person_relationships(
    person_id: str,
    session: AsyncSession = DbDep,
):
    """All relationships for a person with detailed scores."""
    try:
        rels = await relationship_engine.get_relationships(session, person_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to get relationships for %s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return {
        "person_id": person_id,
        "relationships": rels,
        "count": len(rels),
    }


@router.get("/persons/{person_id}/family-tree")
async def person_family_tree(
    person_id: str,
    session: AsyncSession = DbDep,
):
    """Hierarchical family structure for a person."""
    try:
        tree = await relationship_engine.get_family_tree(session, person_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to build family tree for %s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return tree


@router.get("/persons/{person_id}/network")
async def person_full_network(
    person_id: str,
    depth: int = Query(2, ge=1, le=3, description="Graph depth"),
    session: AsyncSession = DbDep,
):
    """Full network graph (family + social + professional) for visualization."""
    try:
        network = await relationship_engine.build_network_for_visualization(
            session, person_id, max_depth=depth
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to build network for %s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return network


@router.post("/persons/{person_id}/expand-relationships")
async def expand_person_relationships(
    person_id: str,
    req: ExpandRelationshipsRequest | None = None,
    session: AsyncSession = DbDep,
):
    """Trigger deeper relationship discovery for a person."""
    depth = req.depth if req else 2
    try:
        await event_bus.publish("graph", {
            "event": "expand_relationships",
            "person_id": person_id,
            "depth": depth,
            "source": "manual_expansion",
        })
    except Exception:
        logger.warning("Could not publish expansion event (no Redis?)")

    return {
        "person_id": person_id,
        "message": f"Relationship expansion queued (depth={depth})",
        "depth": depth,
    }


@router.get("/persons/{person_id}/relationship-score/{other_id}")
async def relationship_score(
    person_id: str,
    other_id: str,
    session: AsyncSession = DbDep,
):
    """Score between two specific people."""
    try:
        score = await relationship_engine.get_relationship_score(
            session, person_id, other_id
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to get score %s <-> %s", person_id, other_id)
        raise HTTPException(500, "Internal error") from exc

    return {
        "person_a": person_id,
        "person_b": other_id,
        **score,
    }


# ── Graph visualization endpoint ──────────────────────────────────────────


@router.get("/graph/person/{person_id}/network")
async def graph_person_network(
    person_id: str,
    depth: int = Query(2, ge=1, le=3),
    session: AsyncSession = DbDep,
):
    """Graph visualization data with full relationship metadata.

    Returns the format expected by the interactive graph:
    {center, nodes, edges, stats}
    """
    try:
        network = await relationship_engine.build_network_for_visualization(
            session, person_id, max_depth=depth
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to build graph network for %s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return network


# ── Manual relationship management ─────────────────────────────────────────


@router.post("/relationships")
async def add_relationship(
    req: AddRelationshipRequest,
    session: AsyncSession = DbDep,
):
    """Manually add or update a relationship between two persons."""
    try:
        result = await relationship_engine.add_relationship(
            session,
            person_a_id=req.person_a_id,
            person_b_id=req.person_b_id,
            raw_label=req.relationship_type,
            source=req.source,
            evidence=req.evidence,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to add relationship")
        raise HTTPException(500, "Internal error") from exc

    return result
