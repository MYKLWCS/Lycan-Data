"""
Verification Engine.

Promotes facts through: UNVERIFIED → CORROBORATED → VERIFIED.
Detects conflicts when sources disagree on the same field.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from shared.constants import VerificationStatus

logger = logging.getLogger(__name__)

CORROBORATION_THRESHOLD = 2  # sources needed for CORROBORATED
CONFLICT_DIVERGENCE = 0.20  # reliability-weighted divergence that triggers conflict flag


@dataclass
class VerificationResult:
    field_name: str
    value: Any
    status: VerificationStatus
    source_count: int
    sources: list[str]
    confidence: float
    conflict: bool = False
    conflict_values: list[Any] = field(default_factory=list)


def verify_field(
    field_name: str,
    observations: list[dict[str, Any]],
) -> VerificationResult:
    """
    Verify a single field across multiple observations.

    Each observation: {value, source, source_reliability}
    Returns a VerificationResult with status and confidence.
    """
    if not observations:
        return VerificationResult(
            field_name=field_name,
            value=None,
            status=VerificationStatus.UNVERIFIED,
            source_count=0,
            sources=[],
            confidence=0.0,
        )

    # Group observations by normalized value
    value_groups: dict[str, list[dict]] = {}
    for obs in observations:
        val = str(obs.get("value", "")).strip().lower()
        value_groups.setdefault(val, []).append(obs)

    # Find the value with highest weighted support
    def _weight(group: list[dict]) -> float:
        return sum(o.get("source_reliability", 0.5) for o in group)

    best_val_key = max(value_groups, key=lambda v: _weight(value_groups[v]))
    best_group = value_groups[best_val_key]
    best_value = best_group[0]["value"]  # original (non-lowercased)

    # Detect conflict: another value has significant weighted support
    conflict = False
    conflict_values = []
    for val, group in value_groups.items():
        if val == best_val_key:
            continue
        if _weight(group) >= CONFLICT_DIVERGENCE:
            conflict = True
            conflict_values.append(group[0]["value"])

    # Determine status
    source_count = len(best_group)
    sources = [o.get("source", "unknown") for o in best_group]

    if source_count >= CORROBORATION_THRESHOLD:
        status = VerificationStatus.CORROBORATED
    else:
        status = VerificationStatus.UNVERIFIED

    # Confidence = average reliability of supporting sources
    confidence = _weight(best_group) / len(best_group)

    return VerificationResult(
        field_name=field_name,
        value=best_value,
        status=status,
        source_count=source_count,
        sources=sources,
        confidence=confidence,
        conflict=conflict,
        conflict_values=conflict_values,
    )


def verify_person(
    person_data: dict[str, Any],
    source_observations: list[dict[str, Any]],
) -> dict[str, VerificationResult]:
    """
    Verify all fields in a person record across multiple source observations.

    source_observations: list of {source, source_reliability, fields: {field_name: value}}
    Returns: {field_name: VerificationResult}
    """
    # Collect per-field observations
    field_obs: dict[str, list[dict]] = {}
    for obs in source_observations:
        source = obs.get("source", "unknown")
        reliability = obs.get("source_reliability", 0.5)
        for field_name, value in obs.get("fields", {}).items():
            if value is not None:
                field_obs.setdefault(field_name, []).append(
                    {
                        "value": value,
                        "source": source,
                        "source_reliability": reliability,
                    }
                )

    return {
        field_name: verify_field(field_name, obs_list) for field_name, obs_list in field_obs.items()
    }


def compute_corroboration_score(results: dict[str, VerificationResult]) -> float:
    """
    Compute an overall corroboration score for a person record.
    0.0 = all unverified, 1.0 = all corroborated, high-reliability.
    """
    if not results:
        return 0.0

    total = sum(
        r.confidence * (1.5 if r.status == VerificationStatus.CORROBORATED else 1.0)
        for r in results.values()
    )
    max_possible = 1.5 * len(results)
    return min(1.0, total / max_possible)


def detect_conflicts(results: dict[str, VerificationResult]) -> list[dict[str, Any]]:
    """Return list of conflict dicts for flagged fields."""
    return [
        {
            "field": name,
            "primary_value": r.value,
            "conflict_values": r.conflict_values,
            "sources": r.sources,
        }
        for name, r in results.items()
        if r.conflict
    ]
