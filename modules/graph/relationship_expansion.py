"""
Relationship Expansion Engine.

Discovers, stores, and scores relationships between persons.
Builds family trees, friend circles, business associations.
Integrates with the knowledge graph and growth daemon.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.person import Alias, Person
from shared.models.relationship import Relationship
from shared.models.relationship_detail import RelationshipDetail

logger = logging.getLogger(__name__)

# ── Relationship type mappings ─────────────────────────────────────────────

# Map source-reported relationship labels to our canonical types
RELATIONSHIP_LABEL_MAP: dict[str, tuple[str, str]] = {
    # (detailed_type, broad_rel_type for Relationship.rel_type)
    "spouse": ("spouse", "family"),
    "wife": ("spouse", "family"),
    "husband": ("spouse", "family"),
    "ex-spouse": ("ex_spouse", "family"),
    "ex-wife": ("ex_spouse", "family"),
    "ex-husband": ("ex_spouse", "family"),
    "parent": ("parent", "family"),
    "mother": ("parent", "family"),
    "father": ("parent", "family"),
    "child": ("child", "family"),
    "son": ("child", "family"),
    "daughter": ("child", "family"),
    "sibling": ("sibling", "family"),
    "brother": ("sibling", "family"),
    "sister": ("sibling", "family"),
    "grandparent": ("grandparent", "family"),
    "grandmother": ("grandparent", "family"),
    "grandfather": ("grandparent", "family"),
    "grandchild": ("grandchild", "family"),
    "grandson": ("grandchild", "family"),
    "granddaughter": ("grandchild", "family"),
    "aunt": ("aunt_uncle", "family"),
    "uncle": ("aunt_uncle", "family"),
    "cousin": ("cousin", "family"),
    "in-law": ("in_law", "family"),
    "mother-in-law": ("in_law", "family"),
    "father-in-law": ("in_law", "family"),
    "sister-in-law": ("in_law", "family"),
    "brother-in-law": ("in_law", "family"),
    "girlfriend": ("girlfriend", "associate"),
    "boyfriend": ("boyfriend", "associate"),
    "partner": ("partner", "associate"),
    "ex-partner": ("ex_partner", "associate"),
    "friend": ("friend", "associate"),
    "best friend": ("best_friend", "associate"),
    "acquaintance": ("acquaintance", "associate"),
    "neighbor": ("neighbor", "cohabitant"),
    "roommate": ("roommate", "cohabitant"),
    "classmate": ("classmate", "associate"),
    "colleague": ("colleague", "employer"),
    "coworker": ("colleague", "employer"),
    "employer": ("employer", "employer"),
    "employee": ("employee", "employee"),
    "business partner": ("business_partner", "business_partner"),
    "co-founder": ("co_founder", "business_partner"),
    "client": ("client", "associate"),
    "mentor": ("mentor", "associate"),
    "lawyer": ("lawyer", "associate"),
    "attorney": ("lawyer", "associate"),
    "co-defendant": ("co_defendant", "associate"),
    "plaintiff": ("plaintiff", "associate"),
    "witness": ("witness", "associate"),
    "co-signer": ("co_signer", "co_signatory"),
    "beneficiary": ("beneficiary", "associate"),
    "trustee": ("trustee", "associate"),
    "power of attorney": ("power_of_attorney", "associate"),
    # Catch-alls from people-search sites
    "relative": ("family", "family"),
    "associate": ("associate", "associate"),
    "possible relative": ("family", "family"),
    "possible associate": ("associate", "associate"),
}

# Strength defaults by type (0-100)
DEFAULT_STRENGTH: dict[str, int] = {
    "spouse": 95, "ex_spouse": 60, "parent": 95, "child": 95, "sibling": 90,
    "grandparent": 85, "grandchild": 85, "aunt_uncle": 70, "cousin": 60,
    "in_law": 65, "girlfriend": 70, "boyfriend": 70, "partner": 80,
    "ex_partner": 40, "friend": 50, "best_friend": 75, "acquaintance": 20,
    "neighbor": 30, "roommate": 60, "classmate": 35, "colleague": 40,
    "employer": 55, "employee": 55, "business_partner": 70, "co_founder": 80,
    "client": 35, "mentor": 45, "lawyer": 50, "co_defendant": 55,
    "plaintiff": 40, "witness": 30, "co_signer": 65, "beneficiary": 60,
    "trustee": 55, "power_of_attorney": 70, "family": 60, "associate": 30,
}

# Confidence by source type (0.0-1.0)
SOURCE_CONFIDENCE: dict[str, float] = {
    "voter_records": 0.90, "property_records": 0.88, "court_records": 0.92,
    "corporate_filings": 0.85, "obituary": 0.80, "familysearch": 0.75,
    "social_media": 0.55, "people_search": 0.65, "truepeoplesearch": 0.62,
    "fastpeoplesearch": 0.62, "whitepages": 0.65, "spokeo": 0.60,
    "linkedin": 0.70, "facebook": 0.55, "instagram": 0.50,
    "phone_shared": 0.70, "email_shared": 0.65, "address_shared": 0.75,
    "breach_data": 0.40, "inference": 0.35, "unknown": 0.30,
}

# ── Relationship color map for visualization ───────────────────────────────

RELATIONSHIP_COLORS: dict[str, str] = {
    "spouse": "#DC2626", "partner": "#DC2626",
    "ex_spouse": "#FCA5A5", "ex_partner": "#FCA5A5",
    "girlfriend": "#EC4899", "boyfriend": "#EC4899",
    "parent": "#2563EB", "child": "#2563EB",
    "sibling": "#60A5FA",
    "grandparent": "#1E3A8A", "grandchild": "#1E3A8A",
    "aunt_uncle": "#0D9488", "cousin": "#0D9488",
    "in_law": "#7C3AED",
    "best_friend": "#16A34A",
    "friend": "#4ADE80",
    "acquaintance": "#BBF7D0",
    "neighbor": "#EAB308", "roommate": "#EAB308",
    "classmate": "#F59E0B",
    "colleague": "#EA580C",
    "employer": "#C2410C", "employee": "#C2410C",
    "business_partner": "#92400E", "co_founder": "#92400E",
    "client": "#78716C", "mentor": "#78716C",
    "lawyer": "#991B1B", "co_defendant": "#991B1B",
    "plaintiff": "#991B1B", "witness": "#991B1B",
    "co_signer": "#CA8A04", "beneficiary": "#CA8A04",
    "trustee": "#CA8A04", "power_of_attorney": "#CA8A04",
    "family": "#2563EB", "associate": "#6B7280",
}


def _classify_relationship(
    raw_label: str,
) -> tuple[str, str]:
    """Classify a raw label into (detailed_type, broad_rel_type)."""
    normalized = raw_label.lower().strip()
    if normalized in RELATIONSHIP_LABEL_MAP:
        return RELATIONSHIP_LABEL_MAP[normalized]
    # Fuzzy match
    for key, val in RELATIONSHIP_LABEL_MAP.items():
        if key in normalized or normalized in key:
            return val
    return ("associate", "associate")


def _compute_composite(strength: int, confidence: float, freshness: float) -> float:
    """Weighted composite score: 40% strength + 40% confidence + 20% freshness."""
    return round(strength * 0.4 + (confidence * 100) * 0.4 + (freshness * 100) * 0.2, 2)


class RelationshipExpansionEngine:
    """Discovers, stores, and manages relationships between persons."""

    async def add_relationship(
        self,
        session: AsyncSession,
        person_a_id: str,
        person_b_id: str,
        raw_label: str,
        source: str = "unknown",
        evidence: dict[str, Any] | None = None,
        relationship_start: datetime | None = None,
        relationship_end: datetime | None = None,
    ) -> dict[str, Any]:
        """Add or update a relationship with detailed metadata.

        Returns the relationship dict with scoring.
        """
        detailed_type, broad_type = _classify_relationship(raw_label)
        strength = DEFAULT_STRENGTH.get(detailed_type, 30)
        confidence = SOURCE_CONFIDENCE.get(source, 0.30)
        freshness = 1.0  # New relationship = fully fresh
        composite = _compute_composite(strength, confidence, freshness)

        a_uuid = uuid.UUID(person_a_id)
        b_uuid = uuid.UUID(person_b_id)

        # Canonical ordering to prevent duplicates
        if str(a_uuid) > str(b_uuid):
            a_uuid, b_uuid = b_uuid, a_uuid

        # Upsert Relationship
        existing = await session.execute(
            select(Relationship).where(
                Relationship.person_a_id == a_uuid,
                Relationship.person_b_id == b_uuid,
                Relationship.rel_type == broad_type,
            )
        )
        rel = existing.scalar_one_or_none()

        if rel:
            # Update score if this source is more confident
            rel.score = max(rel.score or 0.0, confidence)
            rel.last_seen_at = datetime.now(UTC)
            if evidence:
                current_evidence = rel.evidence or {}
                current_evidence[source] = evidence
                rel.evidence = current_evidence
        else:
            rel = Relationship(
                person_a_id=a_uuid,
                person_b_id=b_uuid,
                rel_type=broad_type,
                score=confidence,
                evidence={source: evidence} if evidence else {},
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
            )
            session.add(rel)
            await session.flush()

        # Upsert RelationshipDetail
        detail_existing = await session.execute(
            select(RelationshipDetail).where(
                RelationshipDetail.relationship_id == rel.id
            )
        )
        detail = detail_existing.scalar_one_or_none()

        if detail:
            # Update with new source data
            if confidence > detail.confidence:
                detail.confidence = confidence
                detail.composite_score = _compute_composite(
                    detail.strength, confidence, detail.freshness_score
                )
            sources = detail.discovery_sources or []
            if source not in sources:
                sources.append(source)
                detail.discovery_sources = sources
                detail.source_count = len(sources)
            detail.last_confirmed_at = datetime.now(UTC)
            # Upgrade verification level based on source count
            detail.verification_level = self._verification_level(detail.source_count)
        else:
            detail = RelationshipDetail(
                relationship_id=rel.id,
                detailed_type=detailed_type,
                strength=strength,
                confidence=confidence,
                freshness_score=freshness,
                composite_score=composite,
                discovered_via=source,
                discovery_sources=[source],
                source_count=1,
                verification_level="single_source",
                relationship_start=relationship_start,
                relationship_end=relationship_end,
                last_confirmed_at=datetime.now(UTC),
            )
            session.add(detail)

        return {
            "relationship_id": str(rel.id),
            "person_a_id": str(a_uuid),
            "person_b_id": str(b_uuid),
            "detailed_type": detailed_type,
            "broad_type": broad_type,
            "strength": strength,
            "confidence": confidence,
            "composite_score": composite,
            "source": source,
            "color": RELATIONSHIP_COLORS.get(detailed_type, "#6B7280"),
        }

    def _verification_level(self, source_count: int) -> str:
        if source_count >= 5:
            return "confirmed"
        if source_count >= 3:
            return "cross_referenced"
        if source_count >= 2:
            return "cross_referenced"
        return "single_source"

    async def get_relationships(
        self,
        session: AsyncSession,
        person_id: str,
    ) -> list[dict[str, Any]]:
        """Get all relationships for a person with detailed scoring."""
        pid = uuid.UUID(person_id)
        stmt = select(Relationship, RelationshipDetail).outerjoin(
            RelationshipDetail, RelationshipDetail.relationship_id == Relationship.id
        ).where(
            (Relationship.person_a_id == pid) | (Relationship.person_b_id == pid)
        )
        result = await session.execute(stmt)
        rows = result.all()

        relationships = []
        for rel, detail in rows:
            other_id = str(rel.person_b_id) if rel.person_a_id == pid else str(rel.person_a_id)
            # Load other person's name
            other_result = await session.execute(
                select(Person.full_name, Person.enrichment_score, Person.default_risk_score, Person.profile_image_url)
                .where(Person.id == uuid.UUID(other_id))
            )
            other_row = other_result.first()

            entry: dict[str, Any] = {
                "relationship_id": str(rel.id),
                "person_id": other_id,
                "name": other_row[0] if other_row else None,
                "enrichment_score": other_row[1] if other_row else 0,
                "risk_score": other_row[2] if other_row else 0,
                "photo_url": other_row[3] if other_row else None,
                "rel_type": rel.rel_type,
                "score": rel.score,
                "first_seen": rel.first_seen_at.isoformat() if rel.first_seen_at else None,
                "last_seen": rel.last_seen_at.isoformat() if rel.last_seen_at else None,
            }

            if detail:
                entry.update({
                    "detailed_type": detail.detailed_type,
                    "strength": detail.strength,
                    "confidence": detail.confidence,
                    "freshness_score": detail.freshness_score,
                    "composite_score": detail.composite_score,
                    "discovered_via": detail.discovered_via,
                    "source_count": detail.source_count,
                    "verification_level": detail.verification_level,
                    "last_confirmed": detail.last_confirmed_at.isoformat() if detail.last_confirmed_at else None,
                    "color": RELATIONSHIP_COLORS.get(detail.detailed_type, "#6B7280"),
                })
            else:
                entry.update({
                    "detailed_type": rel.rel_type,
                    "strength": DEFAULT_STRENGTH.get(rel.rel_type, 30),
                    "confidence": rel.score or 0.5,
                    "color": RELATIONSHIP_COLORS.get(rel.rel_type, "#6B7280"),
                })

            relationships.append(entry)

        return relationships

    async def get_family_tree(
        self,
        session: AsyncSession,
        person_id: str,
    ) -> dict[str, Any]:
        """Build hierarchical family structure for a person."""
        family_types = {
            "spouse", "ex_spouse", "parent", "child", "sibling",
            "grandparent", "grandchild", "aunt_uncle", "cousin", "in_law",
            "family",
        }
        all_rels = await self.get_relationships(session, person_id)
        family_rels = [r for r in all_rels if r.get("detailed_type") in family_types]

        # Get root person
        root_result = await session.execute(
            select(Person).where(Person.id == uuid.UUID(person_id))
        )
        root = root_result.scalar_one_or_none()

        tree: dict[str, Any] = {
            "root": {
                "id": person_id,
                "name": root.full_name if root else None,
                "date_of_birth": root.date_of_birth.isoformat() if root and root.date_of_birth else None,
                "gender": root.gender if root else None,
            },
            "parents": [],
            "children": [],
            "siblings": [],
            "spouses": [],
            "grandparents": [],
            "grandchildren": [],
            "extended": [],
        }

        for rel in family_rels:
            entry = {
                "id": rel["person_id"],
                "name": rel.get("name"),
                "relationship": rel["detailed_type"],
                "confidence": rel.get("confidence", 0.5),
                "strength": rel.get("strength", 50),
            }
            dt = rel.get("detailed_type", "")
            if dt == "parent":
                tree["parents"].append(entry)
            elif dt == "child":
                tree["children"].append(entry)
            elif dt == "sibling":
                tree["siblings"].append(entry)
            elif dt in ("spouse", "ex_spouse"):
                tree["spouses"].append(entry)
            elif dt == "grandparent":
                tree["grandparents"].append(entry)
            elif dt == "grandchild":
                tree["grandchildren"].append(entry)
            else:
                tree["extended"].append(entry)

        # Infer missing: if A is parent of B and C, then B and C are siblings
        children_ids = [c["id"] for c in tree["children"]]
        if len(children_ids) >= 2:
            for i, c1 in enumerate(children_ids):
                for c2 in children_ids[i + 1:]:
                    # Check if sibling relationship already exists
                    existing = await session.execute(
                        select(Relationship).where(
                            and_(
                                Relationship.person_a_id.in_([uuid.UUID(c1), uuid.UUID(c2)]),
                                Relationship.person_b_id.in_([uuid.UUID(c1), uuid.UUID(c2)]),
                                Relationship.rel_type == "family",
                            )
                        ).limit(1)
                    )
                    if not existing.scalar_one_or_none():
                        await self.add_relationship(
                            session, c1, c2, "sibling",
                            source="inference",
                            evidence={"inferred_from": f"shared_parent:{person_id}"},
                        )

        return tree

    async def get_relationship_score(
        self,
        session: AsyncSession,
        person_a_id: str,
        person_b_id: str,
    ) -> dict[str, Any]:
        """Get the relationship score between two specific people."""
        a_uuid = uuid.UUID(person_a_id)
        b_uuid = uuid.UUID(person_b_id)

        stmt = select(Relationship, RelationshipDetail).outerjoin(
            RelationshipDetail, RelationshipDetail.relationship_id == Relationship.id
        ).where(
            ((Relationship.person_a_id == a_uuid) & (Relationship.person_b_id == b_uuid))
            | ((Relationship.person_a_id == b_uuid) & (Relationship.person_b_id == a_uuid))
        )
        result = await session.execute(stmt)
        rows = result.all()

        if not rows:
            return {"connected": False, "relationships": []}

        rels = []
        for rel, detail in rows:
            entry = {
                "rel_type": rel.rel_type,
                "score": rel.score,
            }
            if detail:
                entry.update({
                    "detailed_type": detail.detailed_type,
                    "strength": detail.strength,
                    "confidence": detail.confidence,
                    "composite_score": detail.composite_score,
                    "verification_level": detail.verification_level,
                })
            rels.append(entry)

        return {"connected": True, "relationships": rels}

    async def build_network_for_visualization(
        self,
        session: AsyncSession,
        person_id: str,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Build full network graph data for the visualization endpoint.

        Returns the format expected by GET /graph/person/{id}/network:
        {center, nodes, edges, stats}
        """
        pid = uuid.UUID(person_id)

        # Get center person
        center_result = await session.execute(select(Person).where(Person.id == pid))
        center_person = center_result.scalar_one_or_none()
        if not center_person:
            return {"center": None, "nodes": [], "edges": [], "stats": {}}

        center = {
            "id": str(center_person.id),
            "name": center_person.full_name,
            "photo_url": center_person.profile_image_url,
            "enrichment_score": center_person.enrichment_score or 0,
            "age": self._calc_age(center_person.date_of_birth),
            "location": None,  # Would need address join
            "risk_tier": self._risk_tier(center_person.default_risk_score),
        }

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        visited: set[str] = {person_id}
        frontier: set[str] = {person_id}

        for depth in range(1, max_depth + 1):
            if not frontier:
                break
            next_frontier: set[str] = set()

            for current_id in list(frontier):
                rels = await self.get_relationships(session, current_id)
                for rel in rels:
                    other_id = rel["person_id"]
                    if other_id in visited:
                        # Still add the edge
                        edge = self._make_edge(current_id, other_id, rel, depth)
                        if not any(
                            e["source"] == edge["source"] and e["target"] == edge["target"]
                            and e["relationship_type"] == edge["relationship_type"]
                            for e in edges
                        ):
                            edges.append(edge)
                        continue

                    visited.add(other_id)
                    nodes.append(self._make_node(rel, person_id, depth))
                    edges.append(self._make_edge(current_id, other_id, rel, depth))
                    next_frontier.add(other_id)

            frontier = next_frontier

        return {
            "center": center,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes) + 1,  # +1 for center
                "total_edges": len(edges),
                "max_depth": max_depth,
            },
        }

    def _make_node(self, rel: dict[str, Any], center_id: str, distance: int) -> dict[str, Any]:
        detailed_type = rel.get("detailed_type", "associate")
        return {
            "id": rel["person_id"],
            "name": rel.get("name"),
            "photo_url": rel.get("photo_url"),
            "enrichment_score": rel.get("enrichment_score", 0),
            "age": None,
            "location": None,
            "risk_tier": self._risk_tier(rel.get("risk_score", 0)),
            "relationship_to_center": detailed_type,
            "strength": rel.get("strength", 50),
            "confidence": rel.get("confidence", 0.5),
            "distance": distance,
        }

    def _make_edge(self, source_id: str, target_id: str, rel: dict[str, Any], depth: int) -> dict[str, Any]:
        detailed_type = rel.get("detailed_type", "associate")
        confidence = rel.get("confidence", 0.5)
        strength = rel.get("strength", 50)
        color = rel.get("color", RELATIONSHIP_COLORS.get(detailed_type, "#6B7280"))

        if confidence > 0.7:
            style = "solid"
        elif confidence > 0.4:
            style = "dashed"
        else:
            style = "dotted"

        return {
            "source": source_id,
            "target": target_id,
            "relationship_type": detailed_type,
            "strength": strength,
            "confidence": confidence,
            "discovered_via": rel.get("discovered_via", "unknown"),
            "last_confirmed": rel.get("last_confirmed"),
            "color": color,
            "style": style,
        }

    @staticmethod
    def _calc_age(dob) -> int | None:
        if not dob:
            return None
        from datetime import date
        today = date.today()
        age = today.year - dob.year
        if today.month < dob.month or (today.month == dob.month and today.day < dob.day):
            age -= 1
        return age

    @staticmethod
    def _risk_tier(score: float | None) -> str:
        if score is None:
            return "unknown"
        if score >= 0.8:
            return "critical"
        if score >= 0.6:
            return "high"
        if score >= 0.4:
            return "medium"
        return "low"


# Module-level singleton
relationship_engine = RelationshipExpansionEngine()
