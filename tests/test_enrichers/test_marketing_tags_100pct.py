"""
test_marketing_tags_100pct.py — Coverage for Phase 4 scorer elif branches.

Targets:
  - Line 531-532: elif income_estimate >= 60_000 in _score_banking_premium
  - Line 560-561: elif net_worth_estimate >= 500_000 in _score_high_net_worth
  - Line 598-599: elif income_estimate > 0 (not in [25k,80k]) in _score_auto_loan_candidate
  - Line 625-627: elif income_estimate is None in _score_payday_loan_candidate
  - Line 668-669: elif income_estimate >= 80_000 in _score_mortgage_candidate
  - Line 715-717: elif loan_signal_count == 1 in _score_debt_consolidation
"""

from __future__ import annotations

from modules.enrichers.marketing_tags import (
    _score_auto_loan_candidate,
    _score_banking_premium,
    _score_debt_consolidation,
    _score_high_net_worth,
    _score_mortgage_candidate,
    _score_payday_loan_candidate,
)

# ---------------------------------------------------------------------------
# _score_banking_premium — elif income_estimate >= 60_000 (lines 531-532)
# ---------------------------------------------------------------------------


def test_banking_premium_upper_middle_income():
    """70_000 hits elif income_estimate >= 60_000 branch."""
    s, r = _score_banking_premium(70_000, None, False)
    assert s > 0.0
    assert any("upper-middle income" in reason for reason in r)


def test_banking_premium_high_income():
    """110_000 hits if income_estimate >= 100_000 branch (not elif)."""
    s, r = _score_banking_premium(110_000, None, False)
    assert any("high income" in reason for reason in r)


def test_banking_premium_none_income():
    """None income → early return 0.0."""
    s, r = _score_banking_premium(None, None, False)
    assert s == 0.0 and r == []


# ---------------------------------------------------------------------------
# _score_high_net_worth — elif net_worth_estimate >= 500_000 (lines 560-561)
# ---------------------------------------------------------------------------


def test_high_net_worth_500k_to_999k():
    """750_000 hits elif >= 500_000 branch."""
    s, r = _score_high_net_worth(750_000, False, False)
    assert s >= 0.30
    assert any("500K" in reason for reason in r)


def test_high_net_worth_millionaire():
    """1.5M hits if >= 1_000_000 branch."""
    s, r = _score_high_net_worth(1_500_000, False, False)
    assert any("$1M" in reason for reason in r)


def test_high_net_worth_below_500k():
    """100_000 hits else → return 0.0."""
    s, r = _score_high_net_worth(100_000, False, False)
    assert s == 0.0 and r == []


def test_high_net_worth_none():
    """None → early return 0.0."""
    s, r = _score_high_net_worth(None, False, False)
    assert s == 0.0 and r == []


# ---------------------------------------------------------------------------
# _score_auto_loan_candidate — elif income > 0 (lines 598-599)
# ---------------------------------------------------------------------------


def test_auto_loan_income_outside_medium_range():
    """90_000 income (not 25k-80k) hits elif income_estimate > 0 branch."""
    s, r = _score_auto_loan_candidate(True, False, 90_000)
    assert s >= 0.10
    assert any("income signal present" in reason for reason in r)


def test_auto_loan_medium_income_range():
    """50_000 hits the primary income range branch (25k-80k)."""
    s, r = _score_auto_loan_candidate(True, False, 50_000)
    assert any("medium income signal" in reason for reason in r)


def test_auto_loan_no_vehicle():
    """No vehicle → early return 0.0."""
    s, r = _score_auto_loan_candidate(False, False, 50_000)
    assert s == 0.0 and r == []


# ---------------------------------------------------------------------------
# _score_payday_loan_candidate — elif income_estimate is None (lines 625-627)
# ---------------------------------------------------------------------------


def test_payday_loan_no_income_data():
    """income_estimate=None hits elif income_estimate is None branch."""
    s, r = _score_payday_loan_candidate(0.8, False, None)
    assert s >= 0.10
    assert any("no income data" in reason for reason in r)


def test_payday_loan_low_income():
    """income_estimate < 35_000 hits primary income branch."""
    s, r = _score_payday_loan_candidate(0.8, False, 25_000)
    assert any("low income" in reason for reason in r)


def test_payday_loan_low_distress():
    """distress <= 0.5 → early return 0.0."""
    s, r = _score_payday_loan_candidate(0.3, False, None)
    assert s == 0.0 and r == []


# ---------------------------------------------------------------------------
# _score_mortgage_candidate — elif income >= 80_000 (lines 668-669)
# ---------------------------------------------------------------------------


def test_mortgage_income_80k_to_99k():
    """85_000 hits elif income >= 80_000 branch."""
    s, r = _score_mortgage_candidate(True, 85_000)
    assert s >= 0.50
    assert any("high income signal" in reason for reason in r)


def test_mortgage_income_100k_plus():
    """120_000 hits if income >= 100_000 branch."""
    s, r = _score_mortgage_candidate(True, 120_000)
    assert s == 1.0  # clamped


def test_mortgage_income_50k_to_79k():
    """55_000 hits elif income >= 50_000 branch."""
    s, r = _score_mortgage_candidate(False, 55_000)
    assert any("moderate income" in reason for reason in r)


# ---------------------------------------------------------------------------
# _score_debt_consolidation — elif loan_signal_count == 1 (lines 715-717)
# ---------------------------------------------------------------------------


def test_debt_consolidation_single_signal():
    """loan_signal_count==1 hits elif branch."""
    s, r = _score_debt_consolidation(0.8, 0, True, False)
    assert s >= 0.40
    assert any("single loan exposure" in reason for reason in r)


def test_debt_consolidation_multiple_signals():
    """loan_signal_count>=2 hits if branch."""
    s, r = _score_debt_consolidation(0.8, 1, True, True)
    assert any("multiple loan exposure" in reason for reason in r)


def test_debt_consolidation_low_distress():
    """distress <= 0.4 → early return 0.0."""
    s, r = _score_debt_consolidation(0.3, 0, False, False)
    assert s == 0.0 and r == []
