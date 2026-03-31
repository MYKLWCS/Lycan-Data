"""
Tests for Result Ranking & Sorting Engine — Task 30.
15 tests covering scoring, context weights, authority, recency, and convenience functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from modules.enrichers.ranking import (
    AUTHORITY_WEIGHTS,
    RISK_KEYWORDS,
    RankedResult,
    _compute_recency,
    _compute_risk_relevance,
    _context_weights,
    rank_results,
    sort_by_freshness,
    sort_by_risk,
    sort_by_wealth,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _days_ago_iso(days: float) -> str:
    dt = datetime.now(UTC) - timedelta(days=days)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 1. rank_results returns RankedResult objects sorted descending
# ---------------------------------------------------------------------------
def test_rank_results_returns_sorted_ranked_results():
    """rank_results should return a list of RankedResult in descending rank_score order."""
    results = [
        {"composite_quality": 0.3, "source_type": "dark_paste", "scraped_at": _now_iso()},
        {"composite_quality": 0.9, "source_type": "government_registry", "scraped_at": _now_iso()},
        {"composite_quality": 0.6, "source_type": "linkedin", "scraped_at": _now_iso()},
    ]
    ranked = rank_results(results)

    assert all(isinstance(r, RankedResult) for r in ranked)
    scores = [r.rank_score for r in ranked]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 2. higher composite_quality → higher rank
# ---------------------------------------------------------------------------
def test_higher_quality_ranks_higher():
    """With identical source_type and scraped_at, higher quality scores rank first."""
    results = [
        {"composite_quality": 0.2, "source_type": "linkedin", "scraped_at": _now_iso()},
        {"composite_quality": 0.9, "source_type": "linkedin", "scraped_at": _now_iso()},
    ]
    ranked = rank_results(results)
    assert ranked[0].data["composite_quality"] == 0.9


# ---------------------------------------------------------------------------
# 3. risk context weights risk_relevance more than general
# ---------------------------------------------------------------------------
def test_risk_context_weights_risk_relevance_more():
    """The 'risk' context should assign more weight to risk_relevance than 'general'."""
    risk_w = _context_weights("risk")
    general_w = _context_weights("general")
    assert risk_w["risk_relevance"] > general_w["risk_relevance"]


# ---------------------------------------------------------------------------
# 4. risk keywords in data → higher risk_relevance
# ---------------------------------------------------------------------------
def test_risk_keywords_increase_risk_relevance():
    """Items containing risk keywords get a higher risk_relevance score."""
    clean_item = {"description": "normal person with a job"}
    risky_item = {"description": "fraud arrest warrant sanction"}

    clean_score = _compute_risk_relevance(clean_item)
    risky_score = _compute_risk_relevance(risky_item)

    assert risky_score > clean_score


# ---------------------------------------------------------------------------
# 5. no risk keywords → risk_relevance = 0
# ---------------------------------------------------------------------------
def test_no_risk_keywords_zero_relevance():
    """Items with no risk keywords should have risk_relevance = 0.0."""
    item = {"name": "Alice Smith", "city": "Austin", "platform": "linkedin"}
    score = _compute_risk_relevance(item)
    assert score == 0.0


# ---------------------------------------------------------------------------
# 6. recency: scraped just now → close to 1.0
# ---------------------------------------------------------------------------
def test_recency_just_now_is_one():
    """Item scraped moments ago should have recency very close to 1.0."""
    item = {"scraped_at": _now_iso()}
    score = _compute_recency(item)
    assert score == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# 7. recency: scraped 30 days ago → close to 0.0
# ---------------------------------------------------------------------------
def test_recency_thirty_days_ago_is_zero():
    """Item scraped 30+ days ago should have recency close to 0.0."""
    item = {"scraped_at": _days_ago_iso(30)}
    score = _compute_recency(item)
    assert score == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# 8. recency: ISO string scraped_at parsed correctly
# ---------------------------------------------------------------------------
def test_recency_iso_string_parsed():
    """ISO string scraped_at (including Z suffix) should be parsed without error."""
    item = {"scraped_at": "2026-03-09T12:00:00Z"}  # ~15 days ago from 2026-03-24
    score = _compute_recency(item)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# 9. recency: no scraped_at → 0.5
# ---------------------------------------------------------------------------
def test_recency_missing_scraped_at_returns_half():
    """When scraped_at is absent, recency should default to 0.5."""
    item = {"platform": "twitter", "handle": "user"}
    score = _compute_recency(item)
    assert score == 0.5


# ---------------------------------------------------------------------------
# 10. authority: government_registry → 1.0
# ---------------------------------------------------------------------------
def test_authority_government_registry_is_one():
    """government_registry source should have the highest authority weight of 1.0."""
    assert AUTHORITY_WEIGHTS["government_registry"] == 1.0


# ---------------------------------------------------------------------------
# 11. authority: unknown source → 0.20
# ---------------------------------------------------------------------------
def test_authority_unknown_source_is_lowest():
    """unknown source type should fall back to 0.20 authority weight."""
    results = [{"source_type": "some_totally_unknown_source", "scraped_at": _now_iso()}]
    ranked = rank_results(results)
    assert ranked[0].score_breakdown["authority"] == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# 12. custom weights override defaults
# ---------------------------------------------------------------------------
def test_custom_weights_override_defaults():
    """Passing custom weights should change the score compared to defaults."""
    results = [{"composite_quality": 0.8, "source_type": "dark_paste", "scraped_at": _now_iso()}]

    default_ranked = rank_results(results)
    custom_ranked = rank_results(
        results, weights={"quality": 1.0, "authority": 0.0, "risk_relevance": 0.0, "recency": 0.0}
    )

    assert custom_ranked[0].rank_score != default_ranked[0].rank_score
    # With quality weight=1.0 and quality=0.8, score should be 0.8
    assert custom_ranked[0].rank_score == pytest.approx(0.8, abs=0.001)


# ---------------------------------------------------------------------------
# 13. sort_by_risk, sort_by_wealth, sort_by_freshness convenience functions
# ---------------------------------------------------------------------------
def test_convenience_functions_return_ranked_results():
    """All three convenience functions should return non-empty lists of RankedResult."""
    results = [
        {"composite_quality": 0.7, "source_type": "court_record", "scraped_at": _now_iso()},
        {"composite_quality": 0.4, "source_type": "instagram", "scraped_at": _days_ago_iso(5)},
    ]
    risk = sort_by_risk(results)
    wealth = sort_by_wealth(results)
    fresh = sort_by_freshness(results)

    assert all(isinstance(r, RankedResult) for r in risk)
    assert all(isinstance(r, RankedResult) for r in wealth)
    assert all(isinstance(r, RankedResult) for r in fresh)
    assert len(risk) == 2
    assert len(wealth) == 2
    assert len(fresh) == 2


# ---------------------------------------------------------------------------
# 14. rank_score capped at 1.0
# ---------------------------------------------------------------------------
def test_rank_score_capped_at_one():
    """No result should ever have a rank_score above 1.0."""
    results = [
        {
            "composite_quality": 1.0,
            "source_type": "government_registry",
            "scraped_at": _now_iso(),
            "description": "fraud warrant sanction arrest conviction drug trafficking",
        }
    ]
    ranked = rank_results(results)
    assert ranked[0].rank_score <= 1.0


# ---------------------------------------------------------------------------
# 15. score_breakdown contains all 4 components
# ---------------------------------------------------------------------------
def test_score_breakdown_has_all_components():
    """Every RankedResult should include quality, authority, risk_relevance, and recency."""
    results = [{"composite_quality": 0.6, "source_type": "linkedin", "scraped_at": _now_iso()}]
    ranked = rank_results(results)
    breakdown = ranked[0].score_breakdown

    assert "quality" in breakdown
    assert "authority" in breakdown
    assert "risk_relevance" in breakdown
    assert "recency" in breakdown


# ---------------------------------------------------------------------------
# Bonus: empty results list → returns empty list
# ---------------------------------------------------------------------------
def test_empty_results_returns_empty():
    """rank_results([]) should return an empty list without error."""
    ranked = rank_results([])
    assert ranked == []


# ---------------------------------------------------------------------------
# sort_by_freshness prioritises recently scraped items
# ---------------------------------------------------------------------------
def test_sort_by_freshness_ranks_recent_first():
    """sort_by_freshness should put the most recently scraped result first."""
    results = [
        {
            "composite_quality": 0.9,
            "source_type": "government_registry",
            "scraped_at": _days_ago_iso(20),
        },
        {"composite_quality": 0.1, "source_type": "dark_paste", "scraped_at": _now_iso()},
    ]
    ranked = sort_by_freshness(results)
    # The freshly scraped dark_paste (recency≈1.0) should beat old gov registry (recency≈0.33)
    # because recency weight is 0.70
    assert ranked[0].data["source_type"] == "dark_paste"
