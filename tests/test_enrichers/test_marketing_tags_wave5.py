"""
test_marketing_tags_wave5.py — Coverage gap tests for modules/enrichers/marketing_tags.py.

Targets:
  - Lines 468-469: the `elif len(addresses) > 3` branch in HighInterestBorrowerScorer.score()
    (3 < len(addresses) <= 5 → raw -= 7 and signals.append("moderate address instability..."))
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from modules.enrichers.marketing_tags import HighInterestBorrowerScorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_address() -> MagicMock:
    addr = MagicMock()
    addr.country_code = "US"
    return addr


def _make_employment(is_current: bool = True, started_at=None) -> MagicMock:
    emp = MagicMock()
    emp.is_current = is_current
    emp.started_at = started_at
    return emp


# ---------------------------------------------------------------------------
# Lines 468-469: elif len(addresses) > 3 branch
# ---------------------------------------------------------------------------


def test_high_interest_borrower_moderate_address_instability():
    """
    Lines 468-469: 3 < len(addresses) <= 5 triggers:
      raw -= 7
      signals.append("moderate address instability: N addresses")
    """
    scorer = HighInterestBorrowerScorer()

    # 4 addresses: > 3 and <= 5 → hits the elif branch
    addresses = [_make_address() for _ in range(4)]
    employment = [_make_employment(is_current=True)]

    result = scorer.score(
        criminals=[],
        addresses=addresses,
        employment=employment,
        wealth=None,
    )

    assert any("moderate address instability" in s for s in result.signals)
    # raw starts at 100, -7 for moderate instability, -10 for employment tenure < 1yr (if started_at None)
    # employment.started_at is None → no tenure penalty applied (no started_at → no deduction)
    assert result.score <= 100


def test_high_interest_borrower_moderate_instability_score_reduction():
    """
    Lines 468-469: Verify the -7 deduction is applied (moderate branch, not high branch).
    Compare result with 0 addresses to see the -7 difference.
    """
    scorer = HighInterestBorrowerScorer()

    # Score with 0 addresses — no instability penalty
    result_no_addresses = scorer.score(
        criminals=[],
        addresses=[],
        employment=[_make_employment(is_current=True)],
        wealth=None,
    )

    # Score with 4 addresses — moderate instability: -7
    result_moderate = scorer.score(
        criminals=[],
        addresses=[_make_address() for _ in range(4)],
        employment=[_make_employment(is_current=True)],
        wealth=None,
    )

    # Moderate should be 7 points lower than no-addresses (all else equal)
    assert result_no_addresses.score - result_moderate.score == 7


def test_high_interest_borrower_five_addresses_still_moderate():
    """
    Lines 468-469: Exactly 5 addresses → still in the elif branch (> 3, not > 5).
    """
    scorer = HighInterestBorrowerScorer()
    addresses = [_make_address() for _ in range(5)]

    result = scorer.score(
        criminals=[],
        addresses=addresses,
        employment=[_make_employment(is_current=True)],
        wealth=None,
    )

    assert any("moderate address instability" in s for s in result.signals)
    assert not any("high address instability" in s for s in result.signals)


def test_high_interest_borrower_six_addresses_hits_high_branch():
    """
    Verify 6 addresses hits the if len(addresses) > 5 branch (not the elif).
    Complementary test to confirm branch boundary behavior.
    """
    scorer = HighInterestBorrowerScorer()
    addresses = [_make_address() for _ in range(6)]

    result = scorer.score(
        criminals=[],
        addresses=addresses,
        employment=[_make_employment(is_current=True)],
        wealth=None,
    )

    assert any("high address instability" in s for s in result.signals)
    assert not any("moderate address instability" in s for s in result.signals)


def test_high_interest_borrower_three_addresses_no_instability():
    """
    Boundary: exactly 3 addresses → neither branch fires (not > 3).
    """
    scorer = HighInterestBorrowerScorer()
    addresses = [_make_address() for _ in range(3)]

    result = scorer.score(
        criminals=[],
        addresses=addresses,
        employment=[_make_employment(is_current=True)],
        wealth=None,
    )

    assert not any("instability" in s for s in result.signals)
