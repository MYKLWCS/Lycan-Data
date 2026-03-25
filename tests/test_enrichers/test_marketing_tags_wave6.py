"""
test_marketing_tags_wave6.py — Coverage for modules/enrichers/marketing_tags.py

Targets the specific missing lines:
  531-532: _score_banking_premium — income >= 60k (upper-middle branch)
  560-561: _score_high_net_worth — net_worth >= 500k (middle branch)
  598-599: _score_auto_loan_candidate — income > 0 but not in 25k-80k range
  625-627: _score_payday_loan_candidate — income is None (elevated risk signal)
  668-669: _score_mortgage_candidate — income >= 50k (moderate branch)
  715-717: _score_debt_consolidation — loan_signal_count == 1 (single signal)
"""

from __future__ import annotations

import pytest

from modules.enrichers.marketing_tags import (
    _score_auto_loan_candidate,
    _score_banking_premium,
    _score_debt_consolidation,
    _score_high_net_worth,
    _score_mortgage_candidate,
    _score_payday_loan_candidate,
)

# ---------------------------------------------------------------------------
# lines 531-532: _score_banking_premium — upper-middle income branch (60k-99k)
# ---------------------------------------------------------------------------


def test_score_banking_premium_upper_middle_income_branch():
    """Lines 531-532: 60k <= income < 100k → score += 0.20, reason added."""
    score, reasons = _score_banking_premium(
        income_estimate=75_000.0,
        net_worth_estimate=None,
        has_investment_signals=False,
    )
    assert score > 0.0
    assert any("upper-middle income" in r for r in reasons)


def test_score_banking_premium_high_income_branch():
    """Lines 527-529: income >= 100k → score += 0.40."""
    score, reasons = _score_banking_premium(
        income_estimate=150_000.0,
        net_worth_estimate=None,
        has_investment_signals=False,
    )
    assert score > 0.0
    assert any("high income" in r for r in reasons)


# ---------------------------------------------------------------------------
# lines 560-561: _score_high_net_worth — 500k <= net_worth < 1M
# ---------------------------------------------------------------------------


def test_score_high_net_worth_500k_to_1m_branch():
    """Lines 560-561: 500k <= net_worth < 1M → score += 0.30."""
    score, reasons = _score_high_net_worth(
        net_worth_estimate=750_000.0,
        has_property=False,
        has_investment_signals=False,
    )
    assert score > 0.0
    assert any("500K" in r for r in reasons)


def test_score_high_net_worth_below_500k_returns_zero():
    """Lines 563: net_worth < 500k → return 0.0, []."""
    score, reasons = _score_high_net_worth(
        net_worth_estimate=100_000.0,
        has_property=True,
        has_investment_signals=True,
    )
    assert score == 0.0
    assert reasons == []


# ---------------------------------------------------------------------------
# lines 598-599: _score_auto_loan_candidate — income > 0 but outside 25k-80k
# ---------------------------------------------------------------------------


def test_score_auto_loan_candidate_income_outside_medium_range():
    """Lines 598-599: income > 80k → score += 0.10 (not medium range)."""
    score, reasons = _score_auto_loan_candidate(
        has_vehicle=True,
        has_property=False,
        income_estimate=95_000.0,
    )
    assert score > 0.0
    assert any("income signal present" in r for r in reasons)


def test_score_auto_loan_candidate_medium_income_range():
    """Lines 594-596: 25k <= income <= 80k → score += 0.20."""
    score, reasons = _score_auto_loan_candidate(
        has_vehicle=True,
        has_property=False,
        income_estimate=45_000.0,
    )
    assert score > 0.0
    assert any("medium income" in r for r in reasons)


def test_score_auto_loan_candidate_no_vehicle_returns_zero():
    """Lines 584-585: no vehicle → return 0.0, []."""
    score, reasons = _score_auto_loan_candidate(
        has_vehicle=False,
        has_property=False,
        income_estimate=50_000.0,
    )
    assert score == 0.0
    assert reasons == []


# ---------------------------------------------------------------------------
# lines 625-627: _score_payday_loan_candidate — income is None
# ---------------------------------------------------------------------------


def test_score_payday_loan_candidate_income_none_elevated_risk():
    """Lines 625-627: income is None → score += 0.10, elevated risk signal."""
    score, reasons = _score_payday_loan_candidate(
        financial_distress_score=0.7,
        has_property=False,
        income_estimate=None,
    )
    assert score > 0.0
    assert any("no income data" in r for r in reasons)


def test_score_payday_loan_candidate_low_income():
    """Lines 622-624: income < 35k → score += 0.20."""
    score, reasons = _score_payday_loan_candidate(
        financial_distress_score=0.7,
        has_property=False,
        income_estimate=25_000.0,
    )
    assert score > 0.0
    assert any("low income" in r for r in reasons)


def test_score_payday_loan_candidate_low_distress_returns_zero():
    """Lines 612-613: distress <= 0.5 → return 0.0, []."""
    score, reasons = _score_payday_loan_candidate(
        financial_distress_score=0.3,
        has_property=False,
        income_estimate=None,
    )
    assert score == 0.0
    assert reasons == []


# ---------------------------------------------------------------------------
# lines 668-669: _score_mortgage_candidate — income >= 50k (moderate branch)
# ---------------------------------------------------------------------------


def test_score_mortgage_candidate_moderate_income_50k_to_80k():
    """Lines 668-669: 50k <= income < 80k → score += 0.25."""
    score, reasons = _score_mortgage_candidate(
        has_property=True,
        income_estimate=65_000.0,
    )
    assert score > 0.0
    assert any("moderate income" in r for r in reasons)


def test_score_mortgage_candidate_high_income_80k_to_100k():
    """Lines 664-666: 80k <= income < 100k → score += 0.50."""
    score, reasons = _score_mortgage_candidate(
        has_property=True,
        income_estimate=90_000.0,
    )
    assert score > 0.0
    assert any("high income" in r for r in reasons)


def test_score_mortgage_candidate_very_high_income():
    """Lines 661-663: income >= 100k → score += 0.75."""
    score, reasons = _score_mortgage_candidate(
        has_property=False,
        income_estimate=200_000.0,
    )
    assert score > 0.0
    assert any("high income" in r for r in reasons)


# ---------------------------------------------------------------------------
# lines 715-717: _score_debt_consolidation — loan_signal_count == 1
# ---------------------------------------------------------------------------


def test_score_debt_consolidation_single_signal():
    """Lines 715-717: exactly one loan signal → score += 0.15."""
    score, reasons = _score_debt_consolidation(
        financial_distress_score=0.6,
        criminal_count=0,
        has_vehicle=True,  # one signal
        has_property=False,
    )
    assert score > 0.0
    assert any("single loan exposure" in r for r in reasons)


def test_score_debt_consolidation_multiple_signals():
    """Lines 712-714: two or more loan signals → score += 0.30."""
    score, reasons = _score_debt_consolidation(
        financial_distress_score=0.6,
        criminal_count=1,  # signal 1
        has_vehicle=True,  # signal 2
        has_property=False,
    )
    assert score > 0.0
    assert any("multiple loan exposure" in r for r in reasons)


def test_score_debt_consolidation_low_distress_returns_zero():
    """Lines 705-706: distress <= 0.4 → return 0.0, []."""
    score, reasons = _score_debt_consolidation(
        financial_distress_score=0.2,
        criminal_count=2,
        has_vehicle=True,
        has_property=True,
    )
    assert score == 0.0
    assert reasons == []
