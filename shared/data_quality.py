"""
Data quality scoring.

Every row that mixes in DataQualityMixin gets a composite_quality score (0.0-1.0)
computed from:
  - freshness_score      (0.0-1.0) — how recent the data is
  - source_reliability   (0.0-1.0) — how trustworthy the source is
  - corroboration_score  (0.0-1.0) — how many sources confirm the fact
  - conflict_flag        (bool)    — penalises if conflicting data found

Weights:
  freshness      0.35
  reliability    0.30
  corroboration  0.25
  conflict       -0.10 penalty if True
"""

from __future__ import annotations

from datetime import datetime
from math import exp
from typing import TYPE_CHECKING, Any

from shared.constants import SOURCE_RELIABILITY
from shared.freshness import compute_freshness

if TYPE_CHECKING:  # pragma: no cover
    pass

# Composite score weights
WEIGHT_FRESHNESS = 0.35
WEIGHT_RELIABILITY = 0.30
WEIGHT_CORROBORATION = 0.25
CONFLICT_PENALTY = 0.10


def compute_composite_quality(
    freshness_score: float,
    source_reliability: float,
    corroboration_score: float,
    conflict_flag: bool = False,
) -> float:
    """
    Compute composite quality score from components.

    Args:
        freshness_score: 0.0-1.0
        source_reliability: 0.0-1.0
        corroboration_score: 0.0-1.0
        conflict_flag: True applies a penalty

    Returns:
        float in [0.0, 1.0]
    """
    # Weighted components sum to 0.90 max; the remaining 0.10 is the
    # conflict-free bonus — erased by CONFLICT_PENALTY when a conflict exists.
    score = (
        WEIGHT_FRESHNESS * freshness_score
        + WEIGHT_RELIABILITY * source_reliability
        + WEIGHT_CORROBORATION * corroboration_score
        + CONFLICT_PENALTY  # baseline bonus, cancelled out on conflict
    )
    if conflict_flag:
        score -= CONFLICT_PENALTY
    return round(min(1.0, max(0.0, score)), 4)


def corroboration_score_from_count(count: int) -> float:
    """
    Sigmoid: count=1→0.50, count=2→0.73, count=3→0.88, count=5→0.98

    Replaces the previous log curve. The sigmoid gives more meaningful
    separation at low counts (1-3 sources) which is the practical range
    for most OSINT records. Reaches ~1.0 at 5 sources instead of 10.
    """
    if count <= 0:
        return 0.0
    return round(min(1.0, 1 / (1 + exp(-1.0 * (count - 1)))), 4)


def get_source_reliability(source_name: str) -> float:
    """Look up source reliability by name (fuzzy match against known sources)."""
    source_lower = source_name.lower()
    for key, score in SOURCE_RELIABILITY.items():
        if key in source_lower or source_lower in key:
            return score
    return SOURCE_RELIABILITY["unknown"]


def assess_quality(
    last_scraped_at: datetime | None,
    source_type: str,
    source_name: str,
    corroboration_count: int = 1,
    conflict_flag: bool = False,
) -> dict[str, float | bool | str]:
    """
    Compute all quality dimensions for a data row.

    Returns a dict ready to apply to a DataQualityMixin model.
    """
    freshness = compute_freshness(last_scraped_at, source_type)
    reliability = get_source_reliability(source_name)
    corroboration = corroboration_score_from_count(corroboration_count)
    composite = compute_composite_quality(freshness, reliability, corroboration, conflict_flag)

    return {
        "freshness_score": freshness,
        "source_reliability": reliability,
        "corroboration_count": corroboration_count,
        "corroboration_score": corroboration,
        "conflict_flag": conflict_flag,
        "composite_quality": composite,
        "data_quality": {
            "freshness": freshness,
            "reliability": reliability,
            "corroboration": corroboration,
            "composite": composite,
            "conflict": conflict_flag,
            "source_type": source_type,
            "source_name": source_name,
        },
    }


def apply_quality_to_model(model: Any, **kwargs: Any) -> None:
    """
    Compute and apply quality scores to a DataQualityMixin model instance.

    Usage:
        apply_quality_to_model(
            record,
            last_scraped_at=datetime.utcnow(),
            source_type="social_media_profile",
            source_name="instagram",
            corroboration_count=2,
        )
    """
    quality = assess_quality(**kwargs)
    for field, value in quality.items():
        if hasattr(model, field):
            setattr(model, field, value)
