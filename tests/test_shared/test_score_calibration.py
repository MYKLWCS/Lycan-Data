"""Tests for the sigmoid corroboration score calibration."""

import pytest
from shared.data_quality import corroboration_score_from_count


def test_count_zero_returns_zero():
    assert corroboration_score_from_count(0) == 0.0


def test_count_negative_returns_zero():
    assert corroboration_score_from_count(-5) == 0.0


def test_count_1_near_0_50():
    score = corroboration_score_from_count(1)
    assert 0.49 <= score <= 0.51, f"Expected ~0.50, got {score}"


def test_count_2_near_0_73():
    score = corroboration_score_from_count(2)
    assert 0.71 <= score <= 0.75, f"Expected ~0.73, got {score}"


def test_count_3_near_0_88():
    score = corroboration_score_from_count(3)
    assert 0.86 <= score <= 0.90, f"Expected ~0.88, got {score}"


def test_count_5_near_0_98():
    score = corroboration_score_from_count(5)
    assert 0.96 <= score <= 1.0, f"Expected ~0.98, got {score}"


def test_score_never_exceeds_1():
    for n in range(1, 100):
        assert corroboration_score_from_count(n) <= 1.0


def test_score_monotonically_increasing():
    scores = [corroboration_score_from_count(n) for n in range(1, 20)]
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], \
            f"Score decreased at count {i+1}: {scores[i]} -> {scores[i+1]}"
