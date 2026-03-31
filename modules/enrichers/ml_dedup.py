"""
Pass 4 — ML-Based Entity Resolution.

When labeled training pairs are available, trains a logistic regression
classifier on feature vectors extracted from record pairs.  Otherwise
falls back to a deterministic rule-based scorer that combines weighted
field-level signals.

Features extracted per pair:
  1. Name Jaro-Winkler similarity
  2. Name token-set overlap (Jaccard)
  3. Address Levenshtein similarity
  4. Phone exact match (binary)
  5. Email exact match (binary)
  6. DOB exact match (binary)
  7. Count of matching attributes (normalized)
  8. Sources-are-different flag (binary)
  9. Age difference (normalized, capped at 10 years)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.enrichers.deduplication import (
    MergeCandidate,
    jaro_winkler_similarity,
    levenshtein_similarity,
    name_similarity,
)

logger = logging.getLogger(__name__)


# ── Feature extraction ───────────────────────────────────────────────────────


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def extract_pair_features(a: dict[str, Any], b: dict[str, Any]) -> list[float]:
    """
    Extract a fixed-length feature vector from two person-shaped dicts.

    Each dict may have: full_name, dob, phones, emails, identifiers,
    addresses, _source.
    """
    features: list[float] = []

    # 1. Name Jaro-Winkler
    name_a = (a.get("full_name") or "").lower()
    name_b = (b.get("full_name") or "").lower()
    jw = jaro_winkler_similarity(name_a, name_b) if name_a and name_b else 0.0
    features.append(jw)

    # 2. Name token-set overlap (Jaccard)
    ns = name_similarity(name_a, name_b) if name_a and name_b else 0.0
    features.append(ns)

    # 3. Address Levenshtein
    addrs_a = a.get("addresses", [])
    addrs_b = b.get("addresses", [])
    addr_sim = 0.0
    if addrs_a and addrs_b:

        def _flat(addr: Any) -> str:
            if isinstance(addr, dict):
                parts = [str(addr.get(k, "")) for k in ("street", "city", "state", "zip")]
                return " ".join(p for p in parts if p).lower().strip()
            return str(addr).lower().strip()

        addr_sim = levenshtein_similarity(_flat(addrs_a[0]), _flat(addrs_b[0]))
    features.append(addr_sim)

    # 4. Phone exact match
    phones_a = {_digits(str(p)) for p in a.get("phones", []) if p}
    phones_b = {_digits(str(p)) for p in b.get("phones", []) if p}
    phone_match = 1.0 if (phones_a & phones_b) - {""} else 0.0
    features.append(phone_match)

    # 5. Email exact match
    emails_a = {str(e).lower().strip() for e in a.get("emails", []) if e}
    emails_b = {str(e).lower().strip() for e in b.get("emails", []) if e}
    email_match = 1.0 if (emails_a & emails_b) - {""} else 0.0
    features.append(email_match)

    # 6. DOB exact match
    dob_a = str(a.get("dob", ""))
    dob_b = str(b.get("dob", ""))
    dob_match = 1.0 if dob_a and dob_b and dob_a == dob_b else 0.0
    features.append(dob_match)

    # 7. Count of matching attributes (normalized)
    match_count = sum(
        [
            1 if name_a and name_b and jw > 0.90 else 0,
            1 if phone_match else 0,
            1 if email_match else 0,
            1 if addr_sim > 0.85 else 0,
            1 if dob_match else 0,
        ]
    )
    features.append(match_count / 5.0)

    # 8. Sources different
    src_a = a.get("_source", "")
    src_b = b.get("_source", "")
    sources_diff = 1.0 if src_a and src_b and src_a != src_b else 0.0
    features.append(sources_diff)

    # 9. Age difference (normalized, capped at 10y)
    age_diff_norm = 0.0
    try:
        d1 = datetime.strptime(dob_a, "%Y-%m-%d")
        d2 = datetime.strptime(dob_b, "%Y-%m-%d")
        age_diff = abs((d1 - d2).days) / 365.25
        age_diff_norm = min(age_diff / 10.0, 1.0)
    except (ValueError, TypeError):
        logger.debug("Invalid DOB pair for ML dedup age feature: %r vs %r", dob_a, dob_b)
    features.append(age_diff_norm)

    return features


FEATURE_NAMES = [
    "name_jw",
    "name_jaccard",
    "addr_levenshtein",
    "phone_exact",
    "email_exact",
    "dob_exact",
    "match_attr_ratio",
    "sources_different",
    "age_diff_norm",
]


# ── Training data ────────────────────────────────────────────────────────────


@dataclass
class LabeledPair:
    record_a: dict[str, Any]
    record_b: dict[str, Any]
    is_match: bool


# ── Rule-based fallback scorer ───────────────────────────────────────────────


RULE_WEIGHTS = {
    "name_jw": 0.25,
    "name_jaccard": 0.10,
    "addr_levenshtein": 0.10,
    "phone_exact": 0.20,
    "email_exact": 0.15,
    "dob_exact": 0.15,
    "match_attr_ratio": 0.05,
    "sources_different": 0.00,  # informational, not a match signal
    "age_diff_norm": 0.00,  # penalty applied separately
}


def rule_based_score(features: list[float]) -> float:
    """
    Weighted sum of feature values using hand-tuned weights.

    Returns a score in [0.0, 1.0].
    """
    score = 0.0
    for feat_val, (_, weight) in zip(features, RULE_WEIGHTS.items()):
        score += feat_val * weight

    # Age-difference penalty: if DOBs are known but differ, penalise
    age_diff = features[8]  # age_diff_norm
    dob_exact = features[5]  # dob_exact
    if age_diff > 0.0 and dob_exact == 0.0:
        score -= age_diff * 0.10

    return max(0.0, min(1.0, score))


# ── ML dedup engine ──────────────────────────────────────────────────────────


class MLDedup:
    """
    Pass 4: ML-based deduplication with rule-based fallback.

    Usage:
        dedup = MLDedup()

        # Option A — rule-based (no training data):
        score, is_match = dedup.predict(record_a, record_b)

        # Option B — train on labeled pairs:
        dedup.add_labeled_pair(rec_a, rec_b, is_match=True)
        dedup.add_labeled_pair(rec_c, rec_d, is_match=False)
        dedup.train()
        score, is_match = dedup.predict(record_e, record_f)
    """

    def __init__(self, match_threshold: float = 0.60) -> None:
        self.match_threshold = match_threshold
        self._model: Any = None
        self._training_pairs: list[LabeledPair] = []
        self._is_trained = False

    # ── Labeled data management ──────────────────────────────────────────

    def add_labeled_pair(
        self,
        record_a: dict[str, Any],
        record_b: dict[str, Any],
        is_match: bool,
    ) -> None:
        self._training_pairs.append(LabeledPair(record_a, record_b, is_match))

    def load_labeled_pairs(self, path: str | Path) -> int:
        """
        Load labeled pairs from a JSONL file.

        Each line: {"record_a": {...}, "record_b": {...}, "is_match": true/false}
        """
        count = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                self.add_labeled_pair(obj["record_a"], obj["record_b"], obj["is_match"])
                count += 1
        logger.info("MLDedup: loaded %d labeled pairs from %s", count, path)
        return count

    # ── Training ─────────────────────────────────────────────────────────

    def train(self) -> dict[str, Any]:
        """
        Train a logistic regression model on labeled pairs.

        Returns training stats. Falls back to rule-based if sklearn
        is unavailable or too few examples.
        """
        if len(self._training_pairs) < 10:
            logger.warning(
                "MLDedup: only %d labeled pairs — using rule-based fallback",
                len(self._training_pairs),
            )
            self._is_trained = False
            return {"method": "rule_based", "reason": "insufficient_training_data"}

        X: list[list[float]] = []
        y: list[int] = []
        for pair in self._training_pairs:
            feats = extract_pair_features(pair.record_a, pair.record_b)
            X.append(feats)
            y.append(1 if pair.is_match else 0)

        try:
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(max_iter=1000, class_weight="balanced")
            model.fit(X, y)
            self._model = model
            self._is_trained = True

            # Quick in-sample accuracy
            preds = model.predict(X)
            accuracy = sum(1 for p, t in zip(preds, y) if p == t) / len(y)

            stats = {
                "method": "logistic_regression",
                "n_examples": len(X),
                "n_positive": sum(y),
                "n_negative": len(y) - sum(y),
                "in_sample_accuracy": round(accuracy, 4),
                "feature_names": FEATURE_NAMES,
                "coefficients": {
                    name: round(float(coef), 4) for name, coef in zip(FEATURE_NAMES, model.coef_[0])
                },
            }
            logger.info("MLDedup: trained model — %s", stats)
            return stats

        except ImportError:
            logger.warning("MLDedup: sklearn not available — using rule-based fallback")
            self._is_trained = False
            return {"method": "rule_based", "reason": "sklearn_not_installed"}

    # ── Prediction ───────────────────────────────────────────────────────

    def predict(
        self,
        record_a: dict[str, Any],
        record_b: dict[str, Any],
    ) -> tuple[float, bool]:
        """
        Predict match probability for a record pair.

        Returns (confidence, is_match).
        """
        features = extract_pair_features(record_a, record_b)

        if self._is_trained and self._model is not None:
            try:
                proba = self._model.predict_proba([features])[0][1]
                return float(proba), proba >= self.match_threshold
            except Exception:
                logger.exception("MLDedup: model prediction failed — falling back to rules")

        # Rule-based fallback
        score = rule_based_score(features)
        return score, score >= self.match_threshold

    def score_candidates(
        self,
        persons: list[dict[str, Any]],
        candidate_pairs: list[dict[str, Any]],
    ) -> list[MergeCandidate]:
        """
        Re-score candidate pairs from previous passes using ML/rules.

        candidate_pairs: list of dicts with record1_id, record2_id keys
        persons: list of person dicts (id-indexed)

        Returns MergeCandidate list filtered by match_threshold.
        """
        # Build id→record lookup
        by_id: dict[str, dict] = {str(p["id"]): p for p in persons}
        results: list[MergeCandidate] = []

        for pair in candidate_pairs:
            id_a = str(pair.get("record1_id", pair.get("id_a", "")))
            id_b = str(pair.get("record2_id", pair.get("id_b", "")))

            rec_a = by_id.get(id_a)
            rec_b = by_id.get(id_b)
            if rec_a is None or rec_b is None:
                continue

            confidence, is_match = self.predict(rec_a, rec_b)
            if is_match:
                results.append(
                    MergeCandidate(
                        id_a=id_a,
                        id_b=id_b,
                        similarity_score=confidence,
                        match_reasons=[f"pass4_ml_score={confidence:.3f}"],
                    )
                )

        results.sort(key=lambda c: c.similarity_score, reverse=True)
        return results
