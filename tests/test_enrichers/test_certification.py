"""
Tests for Data Certification System — Task 34.
15 tests covering compute_coverage, _grade_from_score, certify_person,
and _improvement_actions.
"""

from __future__ import annotations

import pytest

from modules.enrichers.certification import (
    COVERAGE_CATEGORIES,
    CertificateGrade,
    DataCertificate,
    _grade_from_score,
    _improvement_actions,
    certify_person,
    compute_coverage,
)

# ===========================================================================
# Helper fixtures
# ===========================================================================


def _full_person_data() -> dict:
    """A person dict with every coverage field populated."""
    data = {}
    for fields in COVERAGE_CATEGORIES.values():
        for f in fields:
            data[f] = "populated"
    return data


def _empty_person_data() -> dict:
    """An empty person dict."""
    return {}


def _good_metrics(source_count: int = 5, corroborated: int = 3) -> dict:
    return {
        "source_count": source_count,
        "avg_freshness": 0.90,
        "avg_reliability": 0.85,
        "corroborated_fields": corroborated,
        "conflicts": 0,
    }


# ===========================================================================
# 1. compute_coverage — all fields populated → all categories covered
# ===========================================================================


def test_compute_coverage_all_populated():
    """When every field in every category is set, all categories are covered."""
    person = _full_person_data()
    covered, missing, score = compute_coverage(person)
    assert set(covered) == set(COVERAGE_CATEGORIES.keys())
    assert missing == []
    assert score == pytest.approx(1.0)


# ===========================================================================
# 2. compute_coverage — empty person data → all missing, coverage_score=0.0
# ===========================================================================


def test_compute_coverage_empty_data():
    """Empty person dict → all categories missing, score=0.0."""
    covered, missing, score = compute_coverage({})
    assert covered == []
    assert set(missing) == set(COVERAGE_CATEGORIES.keys())
    assert score == pytest.approx(0.0)


# ===========================================================================
# 3. compute_coverage — some categories covered → correct split
# ===========================================================================


def test_compute_coverage_partial():
    """Populate only identity and contact fields → only those two covered."""
    person = {
        "full_name": "John Doe",
        "email": "john@example.com",
    }
    covered, missing, score = compute_coverage(person)
    assert "identity" in covered
    assert "contact" in covered
    assert "social" in missing
    assert "financial" in missing
    assert score == pytest.approx(2 / len(COVERAGE_CATEGORIES))


# ===========================================================================
# 4. coverage_score: 0/9 → 0.0, 9/9 → 1.0
# ===========================================================================


def test_coverage_score_zero_and_full():
    """Boundary coverage scores."""
    _, _, zero_score = compute_coverage({})
    _, _, full_score = compute_coverage(_full_person_data())
    assert zero_score == 0.0
    assert full_score == 1.0


# ===========================================================================
# 5. _grade_from_score: PLATINUM
# ===========================================================================


def test_grade_platinum():
    """0.90 score + 5 sources + 3 corroborated → PLATINUM."""
    grade = _grade_from_score(0.90, 5, 3)
    assert grade == CertificateGrade.PLATINUM


# ===========================================================================
# 6. _grade_from_score: GOLD
# ===========================================================================


def test_grade_gold():
    """0.75 score + 3 sources + 2 corroborated → GOLD."""
    grade = _grade_from_score(0.75, 3, 2)
    assert grade == CertificateGrade.GOLD


# ===========================================================================
# 7. _grade_from_score: SILVER
# ===========================================================================


def test_grade_silver():
    """0.55 score + 2 sources → SILVER."""
    grade = _grade_from_score(0.55, 2, 0)
    assert grade == CertificateGrade.SILVER


# ===========================================================================
# 8. _grade_from_score: BRONZE
# ===========================================================================


def test_grade_bronze():
    """0.35 score + 1 source → BRONZE."""
    grade = _grade_from_score(0.35, 1, 0)
    assert grade == CertificateGrade.BRONZE


# ===========================================================================
# 9. _grade_from_score: UNRATED (low score or no sources)
# ===========================================================================


def test_grade_unrated_low_score():
    """0.20 score → UNRATED (below bronze threshold)."""
    grade = _grade_from_score(0.20, 2, 0)
    assert grade == CertificateGrade.UNRATED


def test_grade_unrated_no_sources():
    """Any score with 0 sources → UNRATED."""
    grade = _grade_from_score(0.90, 0, 0)
    assert grade == CertificateGrade.UNRATED


# ===========================================================================
# 10. certify_person — returns DataCertificate with correct grade
# ===========================================================================


def test_certify_person_returns_certificate():
    """certify_person returns a DataCertificate with grade, score, and person_id."""
    cert = certify_person(
        person_id="test-uuid-001",
        person_data=_full_person_data(),
        quality_metrics=_good_metrics(),
    )
    assert isinstance(cert, DataCertificate)
    assert cert.person_id == "test-uuid-001"
    assert cert.grade in CertificateGrade.__members__.values()
    assert 0.0 <= cert.overall_score <= 1.0
    assert cert.certificate_version == "1.0"


# ===========================================================================
# 11. certify_person — conflicts reduce overall_score
# ===========================================================================


def test_certify_person_conflicts_reduce_score():
    """More conflicts lower the overall score."""
    no_conflict_cert = certify_person(
        "p1",
        _full_person_data(),
        {**_good_metrics(), "conflicts": 0},
    )
    with_conflict_cert = certify_person(
        "p1",
        _full_person_data(),
        {**_good_metrics(), "conflicts": 2},
    )
    assert with_conflict_cert.overall_score < no_conflict_cert.overall_score


# ===========================================================================
# 12. certify_person — conflict penalty capped at 0.20
# ===========================================================================


def test_certify_person_conflict_penalty_capped():
    """Conflict penalty never exceeds 0.20 even with many conflicts."""
    cert_4_conflicts = certify_person(
        "p1",
        _full_person_data(),
        {**_good_metrics(), "conflicts": 4},
    )
    cert_100_conflicts = certify_person(
        "p1",
        _full_person_data(),
        {**_good_metrics(), "conflicts": 100},
    )
    # Both should have same score — penalty capped at 0.20
    assert cert_4_conflicts.overall_score == pytest.approx(
        cert_100_conflicts.overall_score, abs=0.001
    )


# ===========================================================================
# 13. overall_score capped at 1.0
# ===========================================================================


def test_certify_person_score_capped_at_one():
    """overall_score never exceeds 1.0 regardless of input values."""
    cert = certify_person(
        "p1",
        _full_person_data(),
        {
            "source_count": 100,
            "avg_freshness": 1.0,
            "avg_reliability": 1.0,
            "corroborated_fields": 100,
            "conflicts": 0,
        },
    )
    assert cert.overall_score <= 1.0


# ===========================================================================
# 14. improvement_actions — missing categories → correct action strings
# ===========================================================================


def test_improvement_actions_missing_categories():
    """Missing 'criminal' category → action mentions sanctions and darkweb."""
    actions = _improvement_actions(["criminal"], CertificateGrade.BRONZE)
    assert len(actions) >= 1
    joined = " ".join(actions).lower()
    assert "sanctions" in joined or "darkweb" in joined or "court" in joined


# ===========================================================================
# 15. improvement_actions — UNRATED → urgent action prepended
# ===========================================================================


def test_improvement_actions_unrated_urgent_prepended():
    """UNRATED grade → urgent seed enrichment action is first in the list."""
    actions = _improvement_actions(["identity", "contact"], CertificateGrade.UNRATED)
    assert len(actions) >= 1
    assert "URGENT" in actions[0]
