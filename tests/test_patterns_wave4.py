"""
test_patterns_wave4.py — Branch-coverage gap tests for modules/patterns/anomaly.py.

Uncovered lines: 57-58
  statistics.stdev() raises StatisticsError when all values are identical
  -> stdev falls back to 0.0.
"""

from __future__ import annotations

import pytest

from modules.patterns.anomaly import AnomalyResult, StatisticalAnomalyDetector

# ===========================================================================
# StatisticalAnomalyDetector — lines 57-58
# ===========================================================================


class TestStatisticalAnomalyDetectorStdevFallback:
    """Lines 57-58: StatisticsError from statistics.stdev -> stdev = 0.0."""

    def test_stdev_statistics_error_fallback_to_zero(self):
        """Lines 57-58: mock stdev to raise StatisticsError -> stdev=0.0 fallback."""
        import statistics
        from unittest.mock import patch

        detector = StatisticalAnomalyDetector(z_threshold=3.0, iqr_multiplier=1.5)

        entities = [{"id": str(i), "score": float(i)} for i in range(5)]

        def raise_statistics_error(values, *args, **kwargs):
            raise statistics.StatisticsError("not enough data points")

        # Patch statistics.stdev inside the anomaly module
        with patch("modules.patterns.anomaly.statistics.stdev", raise_statistics_error):
            results = detector.detect(entities, "score")

        # With stdev=0 all z-scores are 0.  IQR-only outliers may still fire.
        # The important thing is: no exception was raised.
        assert isinstance(results, list)

    def test_all_identical_values_no_anomaly(self):
        """Uniform data produces no anomaly (stdev=0 -> z=0, IQR=0 -> no fences crossed)."""
        detector = StatisticalAnomalyDetector(z_threshold=3.0, iqr_multiplier=1.5)

        entities = [{"id": str(i), "score": 100.0} for i in range(5)]
        results = detector.detect(entities, "score")
        assert results == []

    def test_mixed_values_produces_anomaly(self):
        """Sanity check: a clear outlier is detected."""
        detector = StatisticalAnomalyDetector(z_threshold=2.0, iqr_multiplier=1.5)

        entities = [
            {"id": "a", "score": 10.0},
            {"id": "b", "score": 11.0},
            {"id": "c", "score": 10.5},
            {"id": "d", "score": 10.2},
            {"id": "e", "score": 10.3},
            {"id": "f", "score": 10.1},
            {"id": "g", "score": 500.0},  # extreme outlier
        ]

        results = detector.detect(entities, "score")
        outlier_ids = [r.entity_id for r in results]
        assert "g" in outlier_ids

    def test_fewer_than_3_entities_returns_empty(self):
        """Line 48-49: < 3 valid pairs -> early return []."""
        detector = StatisticalAnomalyDetector()
        entities = [{"id": "x", "score": 5.0}, {"id": "y", "score": 10.0}]
        assert detector.detect(entities, "score") == []

    def test_non_numeric_values_are_skipped(self):
        """Lines 43-46: non-numeric field values are silently skipped."""
        detector = StatisticalAnomalyDetector()
        entities = [
            {"id": "1", "score": "not-a-number"},
            {"id": "2", "score": None},
            {"id": "3", "score": 5.0},
            {"id": "4", "score": 6.0},
            {"id": "5", "score": 7.0},
        ]
        # Only 3 numeric values; no anomaly expected in normal range.
        results = detector.detect(entities, "score")
        assert isinstance(results, list)

    def test_detect_multi_field_runs_per_field(self):
        """detect_multi_field returns a dict keyed by field name."""
        detector = StatisticalAnomalyDetector()
        entities = [{"id": str(i), "a": float(i), "b": float(i * 2)} for i in range(6)]
        results = detector.detect_multi_field(entities, ["a", "b"])
        assert "a" in results
        assert "b" in results
        assert isinstance(results["a"], list)
        assert isinstance(results["b"], list)
