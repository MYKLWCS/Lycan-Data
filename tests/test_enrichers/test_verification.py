"""Tests for modules/enrichers/verification.py — 15 tests."""
import pytest

from shared.constants import VerificationStatus
from modules.enrichers.verification import (
    VerificationResult,
    CORROBORATION_THRESHOLD,
    verify_field,
    verify_person,
    compute_corroboration_score,
    detect_conflicts,
)


# ─── verify_field ─────────────────────────────────────────────────────────────

def test_verify_field_no_observations():
    """Empty observation list → UNVERIFIED, confidence=0.0, value=None."""
    result = verify_field("full_name", [])
    assert result.status == VerificationStatus.UNVERIFIED
    assert result.confidence == 0.0
    assert result.value is None
    assert result.source_count == 0


def test_verify_field_one_source_unverified():
    """Single source is not enough for CORROBORATED."""
    obs = [{"value": "John Smith", "source": "linkedin", "source_reliability": 0.75}]
    result = verify_field("full_name", obs)
    assert result.status == VerificationStatus.UNVERIFIED
    assert result.source_count == 1


def test_verify_field_two_sources_agree_corroborated():
    """Two sources that agree on a value → CORROBORATED."""
    obs = [
        {"value": "John Smith", "source": "linkedin", "source_reliability": 0.75},
        {"value": "John Smith", "source": "facebook", "source_reliability": 0.60},
    ]
    result = verify_field("full_name", obs)
    assert result.status == VerificationStatus.CORROBORATED
    assert result.source_count == 2


def test_verify_field_conflict_flagged():
    """Two high-reliability sources disagree → conflict=True."""
    obs = [
        {"value": "New York", "source": "linkedin", "source_reliability": 0.75},
        {"value": "Los Angeles", "source": "facebook", "source_reliability": 0.60},
    ]
    result = verify_field("city", obs)
    assert result.conflict is True


def test_verify_field_conflict_values_contains_minority():
    """The minority (conflicting) value appears in conflict_values."""
    obs = [
        {"value": "New York", "source": "linkedin", "source_reliability": 0.75},
        {"value": "New York", "source": "whitepages", "source_reliability": 0.65},
        {"value": "Los Angeles", "source": "facebook", "source_reliability": 0.60},
    ]
    result = verify_field("city", obs)
    assert result.conflict is True
    assert "Los Angeles" in result.conflict_values


def test_verify_field_best_value_highest_weight():
    """The value with the highest total reliability weight is chosen."""
    obs = [
        {"value": "Alice", "source": "government_registry", "source_reliability": 0.95},
        {"value": "Alice", "source": "court_record", "source_reliability": 0.92},
        {"value": "Bob", "source": "dark_paste", "source_reliability": 0.25},
    ]
    result = verify_field("full_name", obs)
    assert result.value == "Alice"
    assert result.status == VerificationStatus.CORROBORATED


def test_verify_field_case_insensitive_grouping():
    """'John' and 'john' are treated as the same value."""
    obs = [
        {"value": "John", "source": "linkedin", "source_reliability": 0.75},
        {"value": "john", "source": "facebook", "source_reliability": 0.60},
    ]
    result = verify_field("first_name", obs)
    assert result.status == VerificationStatus.CORROBORATED
    assert result.source_count == 2


# ─── verify_person ────────────────────────────────────────────────────────────

def test_verify_person_returns_per_field_results():
    """verify_person returns a dict keyed by field name."""
    person = {}
    source_obs = [
        {
            "source": "linkedin",
            "source_reliability": 0.75,
            "fields": {"full_name": "John Smith", "city": "Chicago"},
        },
        {
            "source": "facebook",
            "source_reliability": 0.60,
            "fields": {"full_name": "John Smith", "city": "Chicago"},
        },
    ]
    results = verify_person(person, source_obs)
    assert "full_name" in results
    assert "city" in results
    assert results["full_name"].status == VerificationStatus.CORROBORATED


def test_verify_person_missing_fields_skipped():
    """Fields set to None in observations are excluded gracefully."""
    person = {}
    source_obs = [
        {
            "source": "linkedin",
            "source_reliability": 0.75,
            "fields": {"full_name": "Alice", "dob": None},
        },
    ]
    results = verify_person(person, source_obs)
    assert "full_name" in results
    assert "dob" not in results  # None values are skipped


# ─── compute_corroboration_score ─────────────────────────────────────────────

def test_compute_corroboration_score_all_corroborated():
    """All CORROBORATED high-confidence results → score close to 1.0."""
    results = {
        "full_name": VerificationResult(
            field_name="full_name", value="Alice",
            status=VerificationStatus.CORROBORATED,
            source_count=3, sources=["a", "b", "c"], confidence=0.90,
        ),
        "city": VerificationResult(
            field_name="city", value="NYC",
            status=VerificationStatus.CORROBORATED,
            source_count=2, sources=["a", "b"], confidence=0.85,
        ),
    }
    score = compute_corroboration_score(results)
    assert score > 0.80


def test_compute_corroboration_score_all_unverified():
    """All UNVERIFIED low-confidence results → lower score than corroborated."""
    corroborated_results = {
        "full_name": VerificationResult(
            field_name="full_name", value="Alice",
            status=VerificationStatus.CORROBORATED,
            source_count=2, sources=["a", "b"], confidence=0.90,
        ),
    }
    unverified_results = {
        "full_name": VerificationResult(
            field_name="full_name", value="Alice",
            status=VerificationStatus.UNVERIFIED,
            source_count=1, sources=["a"], confidence=0.30,
        ),
    }
    score_corr = compute_corroboration_score(corroborated_results)
    score_unv = compute_corroboration_score(unverified_results)
    assert score_corr > score_unv


def test_compute_corroboration_score_empty():
    """Empty results dict → 0.0."""
    assert compute_corroboration_score({}) == 0.0


# ─── detect_conflicts ────────────────────────────────────────────────────────

def test_detect_conflicts_returns_conflict_fields():
    """Fields with conflict=True appear in the returned list."""
    results = {
        "city": VerificationResult(
            field_name="city", value="New York",
            status=VerificationStatus.UNVERIFIED,
            source_count=1, sources=["linkedin"], confidence=0.75,
            conflict=True, conflict_values=["Los Angeles"],
        ),
        "full_name": VerificationResult(
            field_name="full_name", value="Alice",
            status=VerificationStatus.CORROBORATED,
            source_count=2, sources=["a", "b"], confidence=0.85,
            conflict=False,
        ),
    }
    conflicts = detect_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "city"
    assert conflicts[0]["primary_value"] == "New York"
    assert "Los Angeles" in conflicts[0]["conflict_values"]


def test_detect_conflicts_no_conflicts_empty_list():
    """No conflicted fields → empty list."""
    results = {
        "full_name": VerificationResult(
            field_name="full_name", value="Alice",
            status=VerificationStatus.CORROBORATED,
            source_count=2, sources=["a", "b"], confidence=0.85,
        ),
    }
    assert detect_conflicts(results) == []


# ─── CORROBORATION_THRESHOLD boundary ────────────────────────────────────────

def test_corroboration_threshold_exactly_two_sources():
    """Exactly CORROBORATION_THRESHOLD (2) sources with same value → CORROBORATED."""
    assert CORROBORATION_THRESHOLD == 2
    obs = [
        {"value": "Austin", "source": "whitepages", "source_reliability": 0.65},
        {"value": "Austin", "source": "truecaller", "source_reliability": 0.70},
    ]
    result = verify_field("city", obs)
    assert result.status == VerificationStatus.CORROBORATED
    assert result.source_count == 2
