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
