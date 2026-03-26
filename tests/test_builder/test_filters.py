"""Tests for modules/builder/filters.py — post-discovery filters."""

from datetime import date
from unittest.mock import MagicMock

from modules.builder.filters import apply_post_filters


def _mock_person(**kwargs):
    p = MagicMock()
    p.date_of_birth = kwargs.get("dob")
    p.estimated_annual_income_usd = kwargs.get("income")
    p.property_count = kwargs.get("property_count", 0)
    p.vehicle_count = kwargs.get("vehicle_count", 0)
    p.default_risk_score = kwargs.get("risk_score", 0.0)
    p.alt_credit_score = kwargs.get("credit_score")
    p.marital_status = kwargs.get("marital_status")
    p.marketing_tags_list = kwargs.get("tags", [])
    p.gender = kwargs.get("gender")
    return p


def test_no_criteria_passes_all():
    person = _mock_person()
    assert apply_post_filters(person, {}) is True


def test_age_range_pass():
    person = _mock_person(dob=date(1990, 6, 15))
    assert apply_post_filters(person, {"age_range": {"min": 30, "max": 45}}) is True


def test_age_range_fail_too_young():
    person = _mock_person(dob=date(2005, 1, 1))
    assert apply_post_filters(person, {"age_range": {"min": 30, "max": 45}}) is False


def test_income_range_pass():
    person = _mock_person(income=75000)
    assert apply_post_filters(person, {"income_range": {"min": 50000, "max": 100000}}) is True


def test_income_range_fail():
    person = _mock_person(income=120000)
    assert apply_post_filters(person, {"income_range": {"min": 50000, "max": 100000}}) is False


def test_property_owner_pass():
    person = _mock_person(property_count=2)
    assert apply_post_filters(person, {"property_owner": True}) is True


def test_property_owner_fail():
    person = _mock_person(property_count=0)
    assert apply_post_filters(person, {"property_owner": True}) is False


def test_has_vehicle_pass():
    person = _mock_person(vehicle_count=1)
    assert apply_post_filters(person, {"has_vehicle": True}) is True


def test_has_vehicle_fail():
    person = _mock_person(vehicle_count=0)
    assert apply_post_filters(person, {"has_vehicle": True}) is False


def test_risk_tier_pass():
    person = _mock_person(risk_score=0.75)
    assert apply_post_filters(person, {"risk_tier": "high"}) is True


def test_risk_tier_fail():
    person = _mock_person(risk_score=0.2)
    assert apply_post_filters(person, {"risk_tier": "high"}) is False


def test_credit_score_range_pass():
    person = _mock_person(credit_score=450)
    assert apply_post_filters(person, {"credit_score_range": {"min": 300, "max": 580}}) is True


def test_credit_score_range_fail():
    person = _mock_person(credit_score=700)
    assert apply_post_filters(person, {"credit_score_range": {"min": 300, "max": 580}}) is False


def test_marital_status_pass():
    person = _mock_person(marital_status="married")
    assert apply_post_filters(person, {"marital_status": "married"}) is True


def test_marital_status_fail():
    person = _mock_person(marital_status="single")
    assert apply_post_filters(person, {"marital_status": "married"}) is False


def test_tags_match():
    person = _mock_person(tags=["title_loan_candidate", "luxury_buyer"])
    assert apply_post_filters(person, {"tags": ["title_loan_candidate"]}) is True


def test_tags_no_match():
    person = _mock_person(tags=["luxury_buyer"])
    assert apply_post_filters(person, {"tags": ["gambling_propensity"]}) is False


def test_combined_filters():
    person = _mock_person(
        dob=date(1988, 3, 20),
        income=85000,
        property_count=1,
        risk_score=0.5,
        marital_status="married",
    )
    criteria = {
        "age_range": {"min": 30, "max": 45},
        "income_range": {"min": 50000, "max": 100000},
        "property_owner": True,
        "risk_tier": "medium",
        "marital_status": "married",
    }
    assert apply_post_filters(person, criteria) is True
