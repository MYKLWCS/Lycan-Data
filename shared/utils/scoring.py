"""Score computation helpers used across modules."""

from __future__ import annotations

import math


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def weighted_sum(scores: dict[str, float], weights: dict[str, float]) -> float:
    """
    Compute weighted sum of scores, clamped to [0, 1].
    Only includes keys present in both dicts.
    """
    total_weight = sum(weights.get(k, 0) for k in scores)
    if total_weight == 0:
        return 0.0
    result = sum(scores[k] * weights.get(k, 0) for k in scores if k in weights)
    return clamp(result / total_weight if total_weight < 1.0 else result)


def log_scale(count: int, base: float = 6.0) -> float:
    """Map a count to a 0-1 score using log scale. log_scale(0)=0, log_scale(∞)→1."""
    if count <= 0:
        return 0.0
    return clamp(math.log(count + 1) / math.log(base + 1))


def tier_from_score(score: float, tiers: list[tuple[float, str]]) -> str:
    """
    Map a score to a tier label.
    tiers: list of (threshold, label) sorted descending by threshold.
    """
    for threshold, label in sorted(tiers, reverse=True):
        if score >= threshold:
            return label
    return tiers[-1][1] if tiers else "unknown"
