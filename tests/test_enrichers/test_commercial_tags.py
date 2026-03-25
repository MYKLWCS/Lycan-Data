"""Phase 4 commercial tags — pure logic tests, no DB required."""

import pytest

from modules.enrichers.marketing_tags import (
    BankingTag,
    InsuranceTag,
    LendingTag,
    WealthTag,
)


def test_insurance_tag_values_exist():
    assert InsuranceTag.INSURANCE_AUTO == "insurance_auto"
    assert InsuranceTag.INSURANCE_LIFE == "insurance_life"
    assert InsuranceTag.INSURANCE_HEALTH == "insurance_health"


def test_banking_tag_values_exist():
    assert BankingTag.BANKING_BASIC == "banking_basic"
    assert BankingTag.BANKING_PREMIUM == "banking_premium"


def test_wealth_tag_values_exist():
    assert WealthTag.HIGH_NET_WORTH == "high_net_worth"


def test_lending_tag_mortgage_candidate_renamed():
    assert LendingTag.MORTGAGE_CANDIDATE == "mortgage"


def test_lending_tag_auto_loan_exists():
    assert LendingTag.AUTO_LOAN_CANDIDATE == "auto_loan_candidate"


def test_lending_tag_debt_consolidation_exists():
    assert LendingTag.DEBT_CONSOLIDATION == "debt_consolidation"


# ── Task 2: _THRESHOLDS entries ───────────────────────────────────────────────

from modules.enrichers.marketing_tags import _THRESHOLDS


def test_thresholds_insurance_auto():
    assert _THRESHOLDS[InsuranceTag.INSURANCE_AUTO] == pytest.approx(0.60)


def test_thresholds_insurance_life():
    assert _THRESHOLDS[InsuranceTag.INSURANCE_LIFE] == pytest.approx(0.65)


def test_thresholds_insurance_health():
    assert _THRESHOLDS[InsuranceTag.INSURANCE_HEALTH] == pytest.approx(0.65)


def test_thresholds_banking_basic():
    assert _THRESHOLDS[BankingTag.BANKING_BASIC] == pytest.approx(0.60)


def test_thresholds_banking_premium():
    assert _THRESHOLDS[BankingTag.BANKING_PREMIUM] == pytest.approx(0.70)


def test_thresholds_high_net_worth():
    assert _THRESHOLDS[WealthTag.HIGH_NET_WORTH] == pytest.approx(0.70)


def test_thresholds_auto_loan_candidate():
    assert _THRESHOLDS[LendingTag.AUTO_LOAN_CANDIDATE] == pytest.approx(0.65)


def test_thresholds_payday_loan_candidate():
    assert _THRESHOLDS[LendingTag.PAYDAY_LOAN_CANDIDATE] == pytest.approx(0.65)


def test_thresholds_personal_loan_candidate():
    assert _THRESHOLDS[LendingTag.PERSONAL_LOAN_CANDIDATE] == pytest.approx(0.60)


def test_thresholds_mortgage_candidate():
    assert _THRESHOLDS[LendingTag.MORTGAGE_CANDIDATE] == pytest.approx(0.70)


def test_thresholds_refinance_candidate():
    assert _THRESHOLDS[LendingTag.REFINANCE_CANDIDATE] == pytest.approx(0.65)


def test_thresholds_debt_consolidation():
    assert _THRESHOLDS[LendingTag.DEBT_CONSOLIDATION] == pytest.approx(0.65)
