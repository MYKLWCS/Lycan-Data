"""
Data Certification System.

Produces a DataCertificate for a person record summarizing overall data quality,
coverage, and trustworthiness. Certificates are:
  PLATINUM  — >= 0.85 overall score, 5+ sources, 3+ corroborated fields
  GOLD      — >= 0.70 overall score, 3+ sources, 2+ corroborated fields
  SILVER    — >= 0.50 overall score, 2+ sources
  BRONZE    — >= 0.30 overall score, 1+ source
  UNRATED   — < 0.30 or no sources
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CertificateGrade(StrEnum):
    PLATINUM = "platinum"
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"
    UNRATED = "unrated"


# Data coverage categories — what we check for
COVERAGE_CATEGORIES = {
    "identity": ["full_name", "dob", "nationality", "gender"],
    "contact": ["phone", "email", "address"],
    "social": ["instagram", "twitter", "facebook", "linkedin"],
    "financial": ["wealth_band", "income_estimate", "default_risk_score"],
    "criminal": ["sanctions_checked", "court_records_checked", "darkweb_exposure"],
    "biographical": ["marital_status", "children_count", "employment"],
    "vehicle": ["vehicle_make", "vehicle_model"],
    "property": ["property_address", "property_value"],
    "psychological": ["ocean_openness", "emotional_triggers"],
}


@dataclass
class DataCertificate:
    person_id: str
    grade: CertificateGrade
    overall_score: float  # 0.0 - 1.0

    # Breakdown
    source_count: int
    corroborated_field_count: int
    conflict_count: int
    avg_freshness: float
    avg_reliability: float

    # Coverage
    covered_categories: list[str] = field(default_factory=list)
    missing_categories: list[str] = field(default_factory=list)
    coverage_score: float = 0.0

    # Metadata
    certified_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    certificate_version: str = "1.0"

    # Recommendations for improving the certificate
    improvement_actions: list[str] = field(default_factory=list)


def compute_coverage(person_data: dict[str, Any]) -> tuple[list[str], list[str], float]:
    """Check which data categories are populated."""
    covered = []
    missing = []

    for category, fields in COVERAGE_CATEGORIES.items():
        has_any = any(person_data.get(f) is not None and person_data.get(f) != "" for f in fields)
        if has_any:
            covered.append(category)
        else:
            missing.append(category)

    coverage_score = len(covered) / len(COVERAGE_CATEGORIES) if COVERAGE_CATEGORIES else 0.0
    return covered, missing, coverage_score


def _grade_from_score(
    overall_score: float,
    source_count: int,
    corroborated_count: int,
) -> CertificateGrade:
    """Determine certificate grade from metrics."""
    if overall_score >= 0.85 and source_count >= 5 and corroborated_count >= 3:
        return CertificateGrade.PLATINUM
    if overall_score >= 0.70 and source_count >= 3 and corroborated_count >= 2:
        return CertificateGrade.GOLD
    if overall_score >= 0.50 and source_count >= 2:
        return CertificateGrade.SILVER
    if overall_score >= 0.30 and source_count >= 1:
        return CertificateGrade.BRONZE
    return CertificateGrade.UNRATED


def _improvement_actions(missing_categories: list[str], grade: CertificateGrade) -> list[str]:
    """Suggest specific scraping actions to improve the certificate grade."""
    actions = []

    action_map = {
        "identity": "Run whitepages + truepeoplesearch for full name/DOB/address",
        "contact": "Run phone enrichment (carrier+truecaller) and email enrichment (holehe+hibp)",
        "social": "Run Instagram, Twitter, LinkedIn, Facebook scrapers",
        "financial": "Run wealth assessment and credit risk scoring",
        "criminal": "Run sanctions_ofac, sanctions_un, court_courtlistener, darkweb_ahmia",
        "biographical": "Run social_posts_analyzer for marital status and children count",
        "vehicle": "Run vehicle_ownership scraper",
        "property": "Run property_zillow and property_county scrapers",
        "psychological": "Run social_posts_analyzer with OCEAN analysis",
    }

    for cat in missing_categories:
        if cat in action_map:
            actions.append(action_map[cat])

    if grade == CertificateGrade.UNRATED:
        actions.insert(0, "URGENT: Start with seed enrichment — run all identity scrapers")

    return actions


def certify_person(
    person_id: str,
    person_data: dict[str, Any],
    quality_metrics: dict[str, Any],
) -> DataCertificate:
    """
    Generate a DataCertificate for a person.

    Args:
        person_id: UUID string
        person_data: All known fields for the person (flat dict)
        quality_metrics: {
            source_count: int,
            avg_freshness: float,
            avg_reliability: float,
            corroborated_fields: int,
            conflicts: int,
        }
    """
    source_count = quality_metrics.get("source_count", 0)
    avg_freshness = quality_metrics.get("avg_freshness", 0.0)
    avg_reliability = quality_metrics.get("avg_reliability", 0.0)
    corroborated = quality_metrics.get("corroborated_fields", 0)
    conflicts = quality_metrics.get("conflicts", 0)

    covered, missing, coverage_score = compute_coverage(person_data)

    # Overall score: weighted combination
    conflict_penalty = min(0.20, conflicts * 0.05)
    overall_score = (
        0.25 * avg_freshness
        + 0.25 * avg_reliability
        + 0.30 * coverage_score
        + 0.20 * min(1.0, corroborated / 5)
        - conflict_penalty
    )
    overall_score = max(0.0, min(1.0, overall_score))

    grade = _grade_from_score(overall_score, source_count, corroborated)
    actions = _improvement_actions(missing, grade)

    return DataCertificate(
        person_id=person_id,
        grade=grade,
        overall_score=overall_score,
        source_count=source_count,
        corroborated_field_count=corroborated,
        conflict_count=conflicts,
        avg_freshness=avg_freshness,
        avg_reliability=avg_reliability,
        covered_categories=covered,
        missing_categories=missing,
        coverage_score=coverage_score,
        improvement_actions=actions,
    )
