"""Tests for modules/enrichers/graph_dedup.py — graph-based entity clustering."""

import pytest

from modules.enrichers.graph_dedup import EntityCluster, GraphDedup, MatchEdge

# ── GraphDedup — basic operations ────────────────────────────────────────────


class TestGraphDedupBasic:
    def test_add_edge_above_threshold(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.80)
        assert g.edge_count == 1
        assert g.node_count == 2

    def test_add_edge_below_threshold_ignored(self):
        g = GraphDedup(confidence_threshold=0.70)
        g.add_edge("a", "b", 0.50)
        assert g.edge_count == 0

    def test_add_self_loop_ignored(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "a", 0.99)
        assert g.edge_count == 0

    def test_clear(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.80)
        g.clear()
        assert g.edge_count == 0
        assert g.node_count == 0


# ── Connected components ─────────────────────────────────────────────────────


class TestFindClusters:
    def test_simple_pair(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.90)
        clusters = g.find_clusters()
        assert len(clusters) == 1
        assert set(clusters[0].record_ids) == {"a", "b"}
        assert clusters[0].avg_confidence == 0.90

    def test_transitive_closure(self):
        """A-B and B-C should form one cluster {A, B, C}."""
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.90)
        g.add_edge("b", "c", 0.85)
        clusters = g.find_clusters()
        assert len(clusters) == 1
        assert set(clusters[0].record_ids) == {"a", "b", "c"}

    def test_two_separate_clusters(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.90)
        g.add_edge("c", "d", 0.88)
        clusters = g.find_clusters()
        assert len(clusters) == 2
        ids = [set(c.record_ids) for c in clusters]
        assert {"a", "b"} in ids
        assert {"c", "d"} in ids

    def test_singletons_excluded(self):
        """Nodes that only appear as self-edges or isolated should not form clusters."""
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.90)
        # "c" is never connected to anything
        clusters = g.find_clusters()
        assert len(clusters) == 1
        assert "c" not in clusters[0].record_ids

    def test_large_cluster(self):
        """Chain: a-b-c-d-e → all in one cluster."""
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.80)
        g.add_edge("b", "c", 0.75)
        g.add_edge("c", "d", 0.82)
        g.add_edge("d", "e", 0.78)
        clusters = g.find_clusters()
        assert len(clusters) == 1
        assert len(clusters[0].record_ids) == 5

    def test_cluster_scoring(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.90)
        g.add_edge("b", "c", 0.80)
        clusters = g.find_clusters()
        assert len(clusters) == 1
        assert clusters[0].avg_confidence == pytest.approx(0.85, abs=0.01)
        assert clusters[0].min_confidence == 0.80

    def test_clusters_sorted_by_size(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edge("a", "b", 0.90)
        g.add_edge("b", "c", 0.85)
        g.add_edge("b", "d", 0.82)
        g.add_edge("x", "y", 0.88)
        clusters = g.find_clusters()
        assert len(clusters) == 2
        assert clusters[0].size >= clusters[1].size


# ── Bulk edge loading ────────────────────────────────────────────────────────


class TestBulkEdges:
    def test_add_edges_from_candidates(self):
        g = GraphDedup(confidence_threshold=0.70)
        candidates = [
            {"id_a": "1", "id_b": "2", "similarity_score": 0.95, "match_reasons": ["name match"]},
            {"id_a": "2", "id_b": "3", "similarity_score": 0.80, "match_reasons": ["dob match"]},
            {"id_a": "4", "id_b": "5", "similarity_score": 0.50},  # below threshold
        ]
        added = g.add_edges_from_candidates(candidates)
        assert added == 2
        assert g.edge_count == 2

    def test_add_edges_preserves_pass_info(self):
        g = GraphDedup(confidence_threshold=0.50)
        g.add_edges_from_candidates(
            [
                {"id_a": "a", "id_b": "b", "similarity_score": 0.90, "pass": 1},
            ]
        )
        clusters = g.find_clusters()
        assert clusters[0].edges[0].source_pass == 1


# ── EntityCluster ────────────────────────────────────────────────────────────


class TestEntityCluster:
    def test_size_property(self):
        cluster = EntityCluster(
            cluster_id="test",
            record_ids=["a", "b", "c"],
            edges=[],
            avg_confidence=0.85,
        )
        assert cluster.size == 3
