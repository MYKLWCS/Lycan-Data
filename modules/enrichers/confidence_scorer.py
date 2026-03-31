"""
Confidence Scoring Algorithm.

Computes a composite confidence score for any data point based on:
  - Base score from source reliability (60% weight)
  - Cross-reference bonus for corroboration (20% weight)
  - Freshness decay based on field TTL (15% weight)
  - Conflict penalty when sources disagree (5% weight)

The final score maps to a verification level:
  >= 0.90 → Certified (4)
  >= 0.70 → Confirmed (3)
  >= 0.50 → Cross-Referenced (2)
  >= 0.30 → Format Valid (1)
  <  0.30 → Unverified (0)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Source reliability weights ───────────────────────────────────────────────

SOURCE_RELIABILITY: dict[str, float] = {
    "ssn_administration": 0.99,
    "state_government": 0.95,
    "federal_government": 0.94,
    "government": 0.94,
    "credit_bureau": 0.90,
    "corporate_registry": 0.88,
    "property_records": 0.85,
    "court_records": 0.82,
    "commercial_database": 0.75,
    "commercial": 0.75,
    "people_search": 0.60,
    "social_media": 0.40,
    "social": 0.40,
    "public_web_scrape": 0.20,
    "web_scrape": 0.20,
    "user_generated": 0.15,
    "unknown": 0.10,
}

# Field-specific TTLs (days before data is considered stale)
FIELD_TTL: dict[str, int] = {
    "phone": 90,
    "email": 180,
    "address": 365,
    "name": 730,
    "full_name": 730,
    "ssn": 7300,
    "ein": 7300,
    "dob": 7300,
    "date_of_birth": 7300,
    "gender": 3650,
    "nationality": 3650,
}


# ── Scoring functions ────────────────────────────────────────────────────────


def score_source_reliability(sources: list[str]) -> float:
    """
    Base score from source reliability.

    Averages the reliability of all contributing sources, then applies
    a multiplicative boost for multiple independent sources agreeing:
      1 source:  1.00x
      2 sources: 1.125x
      3+ sources: 1.25x
    """
    if not sources:
        return 0.0

    scores = [SOURCE_RELIABILITY.get(s.lower(), 0.10) for s in sources]
    base = sum(scores) / len(scores)
    multiplier = 1.0 + min(len(sources) - 1, 2) * 0.125
    return min(base * multiplier, 1.0)


def score_cross_references(num_sources: int) -> float:
    """
    Bonus for cross-references: +0.10 per source, capped at 0.30.
    """
    if num_sources <= 1:
        return 0.0
    return min((num_sources - 1) * 0.10, 0.30)


def score_freshness(field: str, last_verified: str | datetime | None) -> float:
    """
    Freshness score with quadratic decay.

    Formula: (1 - days_old / ttl)^2
    Minimum: 0.20 (very stale data still has some value).
    """
    if last_verified is None:
        return 0.50  # unknown freshness

    try:
        if isinstance(last_verified, str):
            last_dt = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
        else:
            last_dt = last_verified

        if last_dt.tzinfo is None:
            now = datetime.now()
        else:
            now = datetime.now(UTC)

        days_old = max(0, (now - last_dt).days)
    except (ValueError, TypeError):
        return 0.50

    ttl = FIELD_TTL.get(field.lower(), 365)

    if days_old > ttl:
        return 0.20  # very stale

    ratio = 1.0 - (days_old / ttl)
    return max(ratio**2, 0.20)


def score_conflict_penalty(values_and_sources: list[tuple[Any, str]]) -> float:
    """
    Penalty if multiple sources disagree on the same field.

    Returns a negative value (penalty):
      All agree:   0.00
      2 values:   -0.15
      3+ values:  -0.30
    """
    if len(values_and_sources) <= 1:
        return 0.0

    unique_values = set(str(v).lower().strip() for v, _ in values_and_sources)
    if len(unique_values) <= 1:
        return 0.0

    return max(-0.15 * (len(unique_values) - 1), -0.30)


# ── Composite scorer ─────────────────────────────────────────────────────────


@dataclass
class ConfidenceScore:
    """Composite confidence assessment for a data point."""

    field: str
    score: float
    verification_level: int
    level_name: str
    breakdown: dict[str, float]
    sources: list[str]
    num_sources: int


class ConfidenceScorer:
    """
    Compute composite confidence scores for data fields.

    Components and weights:
      60% — Source reliability
      20% — Cross-reference bonus
      15% — Freshness
       5% — Conflict analysis (penalty only)
    """

    def compute(
        self,
        field: str,
        sources: list[str],
        last_verified: str | datetime | None = None,
        conflicting_values: list[tuple[Any, str]] | None = None,
    ) -> ConfidenceScore:
        """
        Compute composite confidence score.

        Args:
            field: field name (e.g. "phone", "email", "address")
            sources: list of source names that contributed this value
            last_verified: ISO timestamp or datetime of last verification
            conflicting_values: list of (value, source) tuples if disagreement exists
        """
        source_score = score_source_reliability(sources)
        xref_score = score_cross_references(len(sources))
        fresh_score = score_freshness(field, last_verified)
        conflict = score_conflict_penalty(conflicting_values or [])

        composite = (
            0.60 * source_score
            + 0.20 * xref_score
            + 0.15 * fresh_score
            + 0.05 * max(conflict, 0)  # only penalise, never negative
        )

        # Apply conflict as a direct subtraction (not weighted)
        if conflict < 0:
            composite = max(0.0, composite + conflict * 0.30)

        composite = max(0.0, min(1.0, composite))

        # Map to verification level
        if composite >= 0.90:
            level = 4
            level_name = "certified"
        elif composite >= 0.70:
            level = 3
            level_name = "confirmed"
        elif composite >= 0.50:
            level = 2
            level_name = "cross_referenced"
        elif composite >= 0.30:
            level = 1
            level_name = "format_valid"
        else:
            level = 0
            level_name = "unverified"

        return ConfidenceScore(
            field=field,
            score=round(composite, 4),
            verification_level=level,
            level_name=level_name,
            breakdown={
                "source_reliability": round(source_score, 4),
                "cross_reference_bonus": round(xref_score, 4),
                "freshness": round(fresh_score, 4),
                "conflict_penalty": round(conflict, 4),
            },
            sources=sources,
            num_sources=len(sources),
        )


# ── Person-level confidence ──────────────────────────────────────────────────


async def compute_person_confidence(
    person_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Compute confidence scores for all identifiers of a person and
    update the person's composite_quality field.

    Returns a summary dict.
    """
    from shared.models.identifier import Identifier
    from shared.models.person import Person

    person = await session.get(Person, person_id)
    if person is None:
        return {"error": f"person {person_id} not found"}

    stmt = select(Identifier).where(Identifier.person_id == person_id)
    result = await session.execute(stmt)
    identifiers = result.scalars().all()

    scorer = ConfidenceScorer()
    field_scores: list[ConfidenceScore] = []

    # Group identifiers by type to detect conflicts
    by_type: dict[str, list] = {}
    for ident in identifiers:
        by_type.setdefault(ident.type, []).append(ident)

    for ident_type, idents in by_type.items():
        sources = [i.scraped_from or "unknown" for i in idents]
        values_and_sources = [
            (i.normalized_value or i.value, i.scraped_from or "unknown") for i in idents
        ]

        # Find most recent scrape timestamp
        timestamps = [i.last_scraped_at for i in idents if i.last_scraped_at]
        last_verified = max(timestamps).isoformat() if timestamps else None

        cs = scorer.compute(
            field=ident_type,
            sources=sources,
            last_verified=last_verified,
            conflicting_values=values_and_sources,
        )
        field_scores.append(cs)

    # Also score person-level fields
    person_sources = [person.scraped_from or "unknown"]
    person_last = person.last_scraped_at.isoformat() if person.last_scraped_at else None

    if person.full_name:
        cs = scorer.compute("full_name", person_sources, person_last)
        field_scores.append(cs)

    if person.date_of_birth:
        cs = scorer.compute("date_of_birth", person_sources, person_last)
        field_scores.append(cs)

    # Compute overall composite quality
    if field_scores:
        overall = sum(s.score for s in field_scores) / len(field_scores)
    else:
        overall = person.composite_quality

    person.composite_quality = round(overall, 4)
    await session.flush()

    logger.info(
        "ConfidenceScorer: person %s composite_quality=%.4f (%d fields scored)",
        person_id,
        overall,
        len(field_scores),
    )

    return {
        "person_id": person_id,
        "composite_quality": round(overall, 4),
        "field_scores": [
            {
                "field": s.field,
                "score": s.score,
                "level": s.verification_level,
                "level_name": s.level_name,
            }
            for s in field_scores
        ],
    }
