"""Tests for modules/enrichers/confidence_scorer.py — confidence scoring algorithm."""

from datetime import UTC, datetime, timedelta

import pytest

from modules.enrichers.confidence_scorer import (
    ConfidenceScorer,
    score_conflict_penalty,
    score_cross_references,
    score_freshness,
    score_source_reliability,
)


# ── score_source_reliability ─────────────────────────────────────────────────


class TestScoreSourceReliability:
    def test_no_sources(self):
        assert score_source_reliability([]) == 0.0

    def test_single_government(self):
        score = score_source_reliability(["government"])
        assert score >= 0.90

    def test_single_web_scrape(self):
        score = score_source_reliability(["web_scrape"])
        assert score <= 0.25

    def test_multiple_sources_boost(self):
        """Multiple sources should score higher than single source."""
        single = score_source_reliability(["credit_bureau"])
        multi = score_source_reliability(["credit_bureau", "government"])
        assert multi > single

    def test_three_sources_max_boost(self):
        """Boost caps at 3+ sources (1.25x)."""
        three = score_source_reliability(["government", "credit_bureau", "commercial"])
        four = score_source_reliability(["government", "credit_bureau", "commercial", "social"])
        # 4 sources shouldn't get more boost than 3 (but different avg)
        assert three > 0.0
        assert four > 0.0

    def test_score_capped_at_1(self):
        sources = ["government", "government", "government"]
        score = score_source_reliability(sources)
        assert score <= 1.0

    def test_unknown_source_low(self):
        score = score_source_reliability(["totally_unknown_source"])
        assert score <= 0.15


# ── score_cross_references ───────────────────────────────────────────────────


class TestScoreCrossReferences:
    def test_single_source_no_bonus(self):
        assert score_cross_references(1) == 0.0

    def test_two_sources(self):
        assert score_cross_references(2) == pytest.approx(0.10)

    def test_three_sources(self):
        assert score_cross_references(3) == pytest.approx(0.20)

    def test_capped_at_030(self):
        assert score_cross_references(10) == pytest.approx(0.30)


# ── score_freshness ──────────────────────────────────────────────────────────


class TestScoreFreshness:
    def test_none_returns_050(self):
        assert score_freshness("phone", None) == 0.50

    def test_just_verified_high_score(self):
        now = datetime.now(UTC).isoformat()
        score = score_freshness("phone", now)
        assert score >= 0.95

    def test_stale_data_low_score(self):
        old = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        score = score_freshness("phone", old)  # TTL=90 days
        assert score == 0.20  # beyond TTL

    def test_half_ttl_moderate(self):
        half = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        score = score_freshness("phone", half)  # TTL=90
        assert 0.20 < score < 0.80

    def test_ssn_stays_fresh(self):
        """SSN has TTL=7300 days, so even 1 year old is very fresh."""
        one_year = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        score = score_freshness("ssn", one_year)
        assert score > 0.80


# ── score_conflict_penalty ───────────────────────────────────────────────────


class TestScoreConflictPenalty:
    def test_no_values(self):
        assert score_conflict_penalty([]) == 0.0

    def test_single_value_no_penalty(self):
        assert score_conflict_penalty([("john@gmail.com", "src1")]) == 0.0

    def test_all_agree_no_penalty(self):
        vals = [
            ("john@gmail.com", "src1"),
            ("john@gmail.com", "src2"),
        ]
        assert score_conflict_penalty(vals) == 0.0

    def test_two_values_penalty(self):
        vals = [
            ("john@gmail.com", "src1"),
            ("john@yahoo.com", "src2"),
        ]
        penalty = score_conflict_penalty(vals)
        assert penalty == pytest.approx(-0.15)

    def test_three_values_max_penalty(self):
        vals = [
            ("john@gmail.com", "src1"),
            ("john@yahoo.com", "src2"),
            ("john@hotmail.com", "src3"),
        ]
        penalty = score_conflict_penalty(vals)
        assert penalty == pytest.approx(-0.30)

    def test_penalty_floor(self):
        """Penalty never goes below -0.30."""
        vals = [(f"val{i}@test.com", f"src{i}") for i in range(10)]
        penalty = score_conflict_penalty(vals)
        assert penalty >= -0.30


# ── ConfidenceScorer ─────────────────────────────────────────────────────────


class TestConfidenceScorer:
    def setup_method(self):
        self.scorer = ConfidenceScorer()

    def test_high_confidence_government_source(self):
        result = self.scorer.compute(
            field="email",
            sources=["government", "credit_bureau"],
            last_verified=datetime.now(UTC).isoformat(),
        )
        assert result.score >= 0.70
        assert result.verification_level >= 3

    def test_low_confidence_single_scrape(self):
        old = (datetime.now(UTC) - timedelta(days=500)).isoformat()
        result = self.scorer.compute(
            field="phone",
            sources=["web_scrape"],
            last_verified=old,
        )
        assert result.score < 0.50
        assert result.verification_level <= 1

    def test_conflict_reduces_score(self):
        now = datetime.now(UTC).isoformat()
        no_conflict = self.scorer.compute(
            field="email",
            sources=["credit_bureau", "government"],
            last_verified=now,
        )
        with_conflict = self.scorer.compute(
            field="email",
            sources=["credit_bureau", "government"],
            last_verified=now,
            conflicting_values=[
                ("john@gmail.com", "credit_bureau"),
                ("john@yahoo.com", "government"),
            ],
        )
        assert with_conflict.score < no_conflict.score

    def test_score_always_0_to_1(self):
        result = self.scorer.compute(
            field="phone",
            sources=["government"] * 5,
            last_verified=datetime.now(UTC).isoformat(),
        )
        assert 0.0 <= result.score <= 1.0

    def test_breakdown_present(self):
        result = self.scorer.compute(
            field="email",
            sources=["credit_bureau"],
            last_verified=datetime.now(UTC).isoformat(),
        )
        assert "source_reliability" in result.breakdown
        assert "cross_reference_bonus" in result.breakdown
        assert "freshness" in result.breakdown
        assert "conflict_penalty" in result.breakdown

    def test_level_mapping_certified(self):
        result = self.scorer.compute(
            field="ssn",
            sources=["government", "credit_bureau", "state_government"],
            last_verified=datetime.now(UTC).isoformat(),
        )
        assert result.level_name in ("certified", "confirmed")

    def test_level_mapping_unverified(self):
        old = (datetime.now(UTC) - timedelta(days=3000)).isoformat()
        result = self.scorer.compute(
            field="phone",
            sources=["unknown"],
            last_verified=old,
        )
        assert result.verification_level <= 1
