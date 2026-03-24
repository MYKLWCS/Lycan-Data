"""Tests for modules/patterns/anomaly.py — StatisticalAnomalyDetector."""

import pytest

from modules.patterns.anomaly import AnomalyResult, StatisticalAnomalyDetector


def _make_entities(values: list[float], field: str = "score") -> list[dict]:
    return [{"id": str(i), field: v} for i, v in enumerate(values)]


# ---------------------------------------------------------------------------
# Basic detection
# ---------------------------------------------------------------------------


def test_no_results_when_fewer_than_three_entities():
    detector = StatisticalAnomalyDetector()
    entities = _make_entities([1.0, 100.0])  # only 2 items
    results = detector.detect(entities, "score")
    assert results == []


def test_returns_only_anomalous_entities():
    # 97 values near 0.5, one extreme outlier
    normal = [0.5] * 97
    entities = _make_entities(normal + [999.0], "score")
    detector = StatisticalAnomalyDetector(z_threshold=3.0)
    results = detector.detect(entities, "score")
    assert len(results) == 1
    assert results[0].value == 999.0
    assert results[0].is_anomaly is True


def test_anomaly_result_fields_populated():
    normal = [1.0] * 50
    entities = _make_entities(normal + [500.0], "score")
    detector = StatisticalAnomalyDetector()
    result = detector.detect(entities, "score")[0]
    assert isinstance(result, AnomalyResult)
    assert result.field == "score"
    assert result.z_score > 0
    assert result.reason != ""
    assert result.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_results_sorted_by_z_score_descending():
    # Two outliers of different magnitudes
    normal = [1.0] * 50
    entities = _make_entities(normal + [200.0, 500.0], "score")
    detector = StatisticalAnomalyDetector()
    results = detector.detect(entities, "score")
    assert len(results) == 2
    assert results[0].z_score >= results[1].z_score


def test_severity_critical_for_extreme_z_score():
    # Very tight cluster + one enormous outlier → z >> 6
    normal = [10.0] * 99
    entities = _make_entities(normal + [100_000.0], "score")
    detector = StatisticalAnomalyDetector()
    results = detector.detect(entities, "score")
    assert results[0].severity == "CRITICAL"


def test_entities_missing_field_are_skipped():
    entities = [
        {"id": "a", "other_field": 1.0},
        {"id": "b"},  # no "score" key
    ] + [{"id": str(i), "score": 1.0} for i in range(20)]
    detector = StatisticalAnomalyDetector()
    # Should not raise; the two bad entities are silently skipped
    results = detector.detect(entities, "score")
    assert isinstance(results, list)


def test_detect_multi_field_returns_per_field_dict():
    normal = [1.0] * 50
    entities = _make_entities(normal + [500.0], "score")
    # Add a second numeric field
    for e in entities:
        e["risk"] = 0.1
    entities[-1]["risk"] = 999.0

    detector = StatisticalAnomalyDetector()
    multi = detector.detect_multi_field(entities, ["score", "risk"])
    assert set(multi.keys()) == {"score", "risk"}
    assert len(multi["score"]) >= 1
    assert len(multi["risk"]) >= 1
