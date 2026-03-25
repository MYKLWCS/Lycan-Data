"""Tests for modules/enrichers/ml_dedup.py — ML/rule-based entity resolution."""

import pytest

from modules.enrichers.ml_dedup import (
    FEATURE_NAMES,
    MLDedup,
    extract_pair_features,
    rule_based_score,
)


# ── Feature extraction ───────────────────────────────────────────────────────


class TestFeatureExtraction:
    def test_feature_count_matches_names(self):
        a = {"full_name": "John Smith", "dob": "1985-03-15", "phones": ["5551234567"]}
        b = {"full_name": "Jon Smith", "dob": "1985-03-15", "phones": ["5551234567"]}
        features = extract_pair_features(a, b)
        assert len(features) == len(FEATURE_NAMES)

    def test_identical_records_high_features(self):
        rec = {
            "full_name": "John Smith",
            "dob": "1985-03-15",
            "phones": ["5551234567"],
            "emails": ["john@example.com"],
        }
        features = extract_pair_features(rec, rec)
        # Name JW should be 1.0
        assert features[0] == 1.0
        # Phone exact match
        assert features[3] == 1.0
        # Email exact match
        assert features[4] == 1.0
        # DOB exact match
        assert features[5] == 1.0

    def test_completely_different_records_low_features(self):
        a = {"full_name": "John Smith", "dob": "1985-03-15", "phones": ["1112223333"]}
        b = {"full_name": "Jane Doe", "dob": "1990-07-22", "phones": ["9998887777"]}
        features = extract_pair_features(a, b)
        # Name JW should be low
        assert features[0] < 0.70
        # Phone: different
        assert features[3] == 0.0
        # DOB: different
        assert features[5] == 0.0

    def test_empty_records(self):
        features = extract_pair_features({}, {})
        assert len(features) == len(FEATURE_NAMES)
        assert all(f == 0.0 for f in features)

    def test_age_diff_normalized(self):
        a = {"full_name": "X", "dob": "1985-01-01"}
        b = {"full_name": "X", "dob": "1990-01-01"}
        features = extract_pair_features(a, b)
        # ~5 years difference / 10 = ~0.5
        assert 0.4 < features[8] < 0.6


# ── Rule-based scoring ───────────────────────────────────────────────────────


class TestRuleBasedScore:
    def test_identical_records_high_score(self):
        rec = {
            "full_name": "John Smith",
            "dob": "1985-03-15",
            "phones": ["5551234567"],
            "emails": ["john@example.com"],
        }
        features = extract_pair_features(rec, rec)
        score = rule_based_score(features)
        assert score >= 0.80

    def test_completely_different_low_score(self):
        a = {"full_name": "John Smith", "dob": "1985-03-15"}
        b = {"full_name": "Jane Doe", "dob": "1990-07-22"}
        features = extract_pair_features(a, b)
        score = rule_based_score(features)
        assert score < 0.50

    def test_score_range_0_to_1(self):
        for _ in range(10):
            features = [0.5] * len(FEATURE_NAMES)
            score = rule_based_score(features)
            assert 0.0 <= score <= 1.0


# ── MLDedup class ────────────────────────────────────────────────────────────


class TestMLDedup:
    def test_predict_rule_based_identical(self):
        """Without training, rule-based fallback should match identical records."""
        ml = MLDedup(match_threshold=0.50)
        rec = {
            "full_name": "John Smith",
            "dob": "1985-03-15",
            "phones": ["5551234567"],
            "emails": ["john@example.com"],
        }
        confidence, is_match = ml.predict(rec, rec)
        assert is_match is True
        assert confidence >= 0.50

    def test_predict_rule_based_different(self):
        ml = MLDedup(match_threshold=0.60)
        a = {"full_name": "John Smith", "dob": "1985-03-15"}
        b = {"full_name": "Jane Doe", "dob": "1990-07-22"}
        confidence, is_match = ml.predict(a, b)
        assert is_match is False

    def test_train_insufficient_data(self):
        ml = MLDedup()
        ml.add_labeled_pair({"full_name": "A"}, {"full_name": "A"}, True)
        stats = ml.train()
        assert stats["method"] == "rule_based"
        assert stats["reason"] == "insufficient_training_data"

    def test_score_candidates(self):
        ml = MLDedup(match_threshold=0.50)
        persons = [
            {"id": "1", "full_name": "John Smith", "dob": "1985-03-15",
             "phones": ["5551234567"], "emails": ["john@example.com"]},
            {"id": "2", "full_name": "John Smith", "dob": "1985-03-15",
             "phones": ["5551234567"], "emails": ["john@example.com"]},
            {"id": "3", "full_name": "Jane Doe", "dob": "1990-07-22",
             "phones": ["9998887777"], "emails": ["jane@example.com"]},
        ]
        pairs = [
            {"id_a": "1", "id_b": "2"},
            {"id_a": "1", "id_b": "3"},
        ]
        results = ml.score_candidates(persons, pairs)
        # Pair 1-2 should match (identical), pair 1-3 probably not
        match_ids = {(c.id_a, c.id_b) for c in results}
        assert ("1", "2") in match_ids

    def test_is_trained_false_by_default(self):
        ml = MLDedup()
        assert ml._is_trained is False
