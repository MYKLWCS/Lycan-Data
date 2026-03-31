"""
Pass 3 — Graph-Based Entity Resolution.

Builds an undirected graph of match edges from Pass 1 & 2 results, then finds
connected components via BFS.  If A matches B and B matches C, clusters A-B-C
as a single entity.

Each component is scored by average internal edge confidence so downstream
consumers can decide whether to auto-merge or route to manual review.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class MatchEdge:
    """A weighted edge between two record IDs."""

    id_a: str
    id_b: str
    confidence: float
    source_pass: int  # 1=exact, 2=fuzzy, 3=graph, 4=ml
    reasons: list[str] = field(default_factory=list)


@dataclass
class EntityCluster:
    """A group of record IDs that resolve to the same real-world entity."""

    cluster_id: str
    record_ids: list[str]
    edges: list[MatchEdge]
    avg_confidence: float = 0.0
    min_confidence: float = 0.0

    @property
    def size(self) -> int:
        return len(self.record_ids)


# ── Graph engine ─────────────────────────────────────────────────────────────


class GraphDedup:
    """
    Pass 3: Build a match graph and find connected components (entity clusters).

    Edges come from Pass 1 (exact) and Pass 2 (fuzzy) results.  The graph
    discovers transitive matches that neither pass would find alone.
    """

    def __init__(self, confidence_threshold: float = 0.50) -> None:
        self.threshold = confidence_threshold
        # adjacency list: record_id → [(neighbor_id, edge)]
        self._adj: dict[str, list[tuple[str, MatchEdge]]] = defaultdict(list)
        self._edges: list[MatchEdge] = []

    # ── Build graph ──────────────────────────────────────────────────────────

    def add_edge(
        self,
        id_a: str,
        id_b: str,
        confidence: float,
        source_pass: int = 2,
        reasons: list[str] | None = None,
    ) -> None:
        """Add an undirected edge if confidence meets threshold."""
        if confidence < self.threshold:
            return
        if id_a == id_b:
            return

        edge = MatchEdge(
            id_a=id_a,
            id_b=id_b,
            confidence=confidence,
            source_pass=source_pass,
            reasons=reasons or [],
        )
        self._adj[id_a].append((id_b, edge))
        self._adj[id_b].append((id_a, edge))
        self._edges.append(edge)

    def add_edges_from_candidates(self, candidates: list[dict[str, Any]]) -> int:
        """
        Bulk-add edges from MergeCandidate-shaped dicts.

        Each dict must have: id_a, id_b, similarity_score.
        Optional: match_reasons (list[str]), pass (int).
        Returns count of edges actually added.
        """
        added = 0
        for c in candidates:
            conf = c.get("similarity_score", 0.0)
            if conf < self.threshold:
                continue
            self.add_edge(
                id_a=str(c["id_a"]),
                id_b=str(c["id_b"]),
                confidence=conf,
                source_pass=c.get("pass", 2),
                reasons=c.get("match_reasons", []),
            )
            added += 1
        return added

    # ── Connected components ─────────────────────────────────────────────────

    def find_clusters(self) -> list[EntityCluster]:
        """
        BFS over the match graph to find connected components.

        Returns a list of EntityCluster objects sorted by size descending.
        Only clusters with 2+ members are returned (singletons are not dupes).
        """
        visited: set[str] = set()
        clusters: list[EntityCluster] = []
        cluster_idx = 0

        for start_node in self._adj:
            if start_node in visited:
                continue

            # BFS
            component_ids: list[str] = []
            component_edges: list[MatchEdge] = []
            queue: deque[str] = deque([start_node])
            visited.add(start_node)

            while queue:
                current = queue.popleft()
                component_ids.append(current)

                for neighbor, edge in self._adj[current]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
                    # Collect edges (deduplicate by checking direction)
                    if edge not in component_edges:
                        component_edges.append(edge)

            if len(component_ids) < 2:
                continue

            # Score the cluster
            confidences = [e.confidence for e in component_edges]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            min_conf = min(confidences) if confidences else 0.0

            clusters.append(
                EntityCluster(
                    cluster_id=f"cluster_{cluster_idx:06d}",
                    record_ids=component_ids,
                    edges=component_edges,
                    avg_confidence=round(avg_conf, 4),
                    min_confidence=round(min_conf, 4),
                )
            )
            cluster_idx += 1

        clusters.sort(key=lambda c: c.size, reverse=True)
        return clusters

    # ── Stats ────────────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self._adj)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def clear(self) -> None:
        self._adj.clear()
        self._edges.clear()


# ── Async DB integration ─────────────────────────────────────────────────────


async def build_graph_from_dedup_reviews(
    session: AsyncSession,
    confidence_threshold: float = 0.50,
) -> GraphDedup:
    """
    Build a match graph from existing DedupReview rows in the database.

    This lets Pass 3 discover transitive clusters across reviews that
    were individually below the auto-merge threshold.
    """
    from shared.models.dedup_review import DedupReview

    graph = GraphDedup(confidence_threshold=confidence_threshold)

    stmt = select(DedupReview).where(
        DedupReview.similarity_score >= confidence_threshold,
    )
    result = await session.execute(stmt)
    reviews = result.scalars().all()

    for review in reviews:
        graph.add_edge(
            id_a=str(review.person_a_id),
            id_b=str(review.person_b_id),
            confidence=review.similarity_score,
            source_pass=2,
            reasons=["dedup_review"],
        )

    logger.info(
        "GraphDedup: built graph with %d nodes, %d edges from %d reviews",
        graph.node_count,
        graph.edge_count,
        len(reviews),
    )
    return graph


async def cluster_persons(
    session: AsyncSession,
    person_ids: list[str] | None = None,
    confidence_threshold: float = 0.70,
) -> list[EntityCluster]:
    """
    High-level entrypoint: run Pass 2 fuzzy matching across a set of persons,
    feed edges into the graph, and return connected-component clusters.

    If person_ids is None, operates on recently-updated persons.
    """
    from modules.enrichers.deduplication import score_person_dedup

    graph = GraphDedup(confidence_threshold=confidence_threshold)

    # If no explicit IDs, grab recent persons
    if person_ids is None:
        from datetime import datetime, timedelta

        from shared.models.person import Person

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        stmt = (
            select(Person.id)
            .where(Person.updated_at >= cutoff)
            .where(Person.merged_into.is_(None))
            .limit(1000)
        )
        result = await session.execute(stmt)
        person_ids = [str(r[0]) for r in result.fetchall()]

    if not person_ids:
        return []

    # Run fuzzy dedup for each person and collect edges
    seen_pairs: set[frozenset[str]] = set()
    for pid in person_ids:
        try:
            candidates = await score_person_dedup(pid, session)
        except Exception:
            logger.exception("GraphDedup: score_person_dedup failed for %s", pid)
            continue

        for c in candidates:
            pair = frozenset({c.id_a, c.id_b})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            graph.add_edge(
                id_a=c.id_a,
                id_b=c.id_b,
                confidence=c.similarity_score,
                source_pass=2,
                reasons=c.match_reasons,
            )

    clusters = graph.find_clusters()
    logger.info(
        "GraphDedup: found %d clusters from %d persons (%d edges)",
        len(clusters),
        len(person_ids),
        graph.edge_count,
    )
    return clusters
