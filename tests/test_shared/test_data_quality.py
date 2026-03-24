from datetime import UTC, datetime, timezone

import pytest

from shared.data_quality import (
    CONFLICT_PENALTY,
    WEIGHT_CORROBORATION,
    WEIGHT_FRESHNESS,
    WEIGHT_RELIABILITY,
    apply_quality_to_model,
    assess_quality,
    compute_composite_quality,
    corroboration_score_from_count,
    get_source_reliability,
)


def test_composite_quality_max():
    score = compute_composite_quality(1.0, 1.0, 1.0, conflict_flag=False)
    assert score == 1.0


def test_composite_quality_conflict_penalty():
    without = compute_composite_quality(0.8, 0.8, 0.8, conflict_flag=False)
    with_conflict = compute_composite_quality(0.8, 0.8, 0.8, conflict_flag=True)
    assert with_conflict == round(without - CONFLICT_PENALTY, 4)


def test_composite_quality_clamped_to_zero():
    score = compute_composite_quality(0.0, 0.0, 0.0, conflict_flag=True)
    assert score == 0.0


def test_corroboration_score_single_source():
    assert corroboration_score_from_count(1) > 0.0
    assert corroboration_score_from_count(1) < 0.5


def test_corroboration_score_increases_with_count():
    scores = [corroboration_score_from_count(i) for i in range(1, 6)]
    assert scores == sorted(scores)  # monotonically increasing


def test_corroboration_score_five_or_more_is_high():
    assert corroboration_score_from_count(5) >= 0.90


def test_corroboration_score_zero():
    assert corroboration_score_from_count(0) == 0.0


def test_get_source_reliability_known():
    score = get_source_reliability("linkedin")
    assert score == 0.75


def test_get_source_reliability_unknown():
    score = get_source_reliability("randomblog123")
    assert score == 0.20


def test_assess_quality_returns_all_fields():
    now = datetime.now(UTC)
    result = assess_quality(
        last_scraped_at=now,
        source_type="social_media_profile",
        source_name="instagram",
        corroboration_count=2,
    )
    required_keys = {
        "freshness_score",
        "source_reliability",
        "corroboration_count",
        "corroboration_score",
        "conflict_flag",
        "composite_quality",
        "data_quality",
    }
    assert required_keys.issubset(result.keys())


def test_apply_quality_to_model():
    class FakeModel:
        freshness_score = 0.0
        source_reliability = 0.0
        corroboration_count = 0
        corroboration_score = 0.0
        conflict_flag = False
        composite_quality = 0.0
        data_quality = {}

    model = FakeModel()
    now = datetime.now(UTC)
    apply_quality_to_model(
        model,
        last_scraped_at=now,
        source_type="social_media_profile",
        source_name="instagram",
        corroboration_count=1,
    )
    assert model.composite_quality > 0.0
    assert model.freshness_score >= 0.99
