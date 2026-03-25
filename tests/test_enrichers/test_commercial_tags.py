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


# ── Task 3: Insurance scorer functions ────────────────────────────────────────

from modules.enrichers.marketing_tags import (
    _score_insurance_auto,
    _score_insurance_health,
    _score_insurance_life,
)


# ── _score_insurance_auto ────────────────────────────────────────────────────


def test_insurance_auto_vehicle_present():
    score, reasons = _score_insurance_auto(has_vehicle=True)
    assert score >= 0.80
    assert any("vehicle" in r.lower() for r in reasons)


def test_insurance_auto_no_vehicle():
    score, reasons = _score_insurance_auto(has_vehicle=False)
    assert score == 0.0
    assert reasons == []


# ── _score_insurance_life ────────────────────────────────────────────────────


def test_insurance_life_age_and_income():
    score, reasons = _score_insurance_life(age=35, income_estimate=60_000.0)
    assert score >= 0.65
    assert any("age" in r.lower() for r in reasons)


def test_insurance_life_age_out_of_range():
    score, _ = _score_insurance_life(age=17, income_estimate=60_000.0)
    assert score < 0.65


def test_insurance_life_no_age():
    score, _ = _score_insurance_life(age=None, income_estimate=None)
    assert score < 0.65


# ── _score_insurance_health ──────────────────────────────────────────────────


def test_insurance_health_employed_adult():
    score, reasons = _score_insurance_health(age=30, is_employed=True)
    assert score >= 0.65
    assert any("employ" in r.lower() for r in reasons)


def test_insurance_health_unemployed():
    score, reasons = _score_insurance_health(age=30, is_employed=False)
    assert score < 0.65


def test_insurance_health_age_out_of_range():
    score, _ = _score_insurance_health(age=17, is_employed=True)
    assert score < 0.65


# ── Task 4: Banking and Wealth scorer functions ────────────────────────────────

from modules.enrichers.marketing_tags import (
    _score_banking_basic,
    _score_banking_premium,
    _score_high_net_worth,
)


# ── _score_banking_basic ─────────────────────────────────────────────────────


def test_banking_basic_employed_adult():
    score, reasons = _score_banking_basic(is_employed=True, age=25)
    assert score >= 0.60
    assert any("employ" in r.lower() for r in reasons)


def test_banking_basic_unemployed():
    score, _ = _score_banking_basic(is_employed=False, age=25)
    assert score < 0.60


def test_banking_basic_minor():
    score, _ = _score_banking_basic(is_employed=False, age=17)
    assert score < 0.60


# ── _score_banking_premium ───────────────────────────────────────────────────


def test_banking_premium_high_income_and_investment():
    score, reasons = _score_banking_premium(
        income_estimate=150_000.0,
        net_worth_estimate=500_000.0,
        has_investment_signals=True,
    )
    assert score >= 0.70
    assert any("income" in r.lower() for r in reasons)


def test_banking_premium_low_income():
    score, _ = _score_banking_premium(
        income_estimate=25_000.0,
        net_worth_estimate=None,
        has_investment_signals=False,
    )
    assert score < 0.70


def test_banking_premium_no_income():
    score, _ = _score_banking_premium(
        income_estimate=None,
        net_worth_estimate=None,
        has_investment_signals=False,
    )
    assert score == 0.0


# ── _score_high_net_worth ────────────────────────────────────────────────────


def test_high_net_worth_all_signals():
    score, reasons = _score_high_net_worth(
        net_worth_estimate=2_000_000.0,
        has_property=True,
        has_investment_signals=True,
    )
    assert score >= 0.70
    assert any("net worth" in r.lower() for r in reasons)


def test_high_net_worth_no_data():
    score, _ = _score_high_net_worth(
        net_worth_estimate=None,
        has_property=False,
        has_investment_signals=False,
    )
    assert score == 0.0


def test_high_net_worth_below_threshold():
    score, _ = _score_high_net_worth(
        net_worth_estimate=50_000.0,
        has_property=False,
        has_investment_signals=False,
    )
    assert score < 0.70


# ── Task 5: Lending scorer functions ─────────────────────────────────────────

from modules.enrichers.marketing_tags import (
    _score_auto_loan_candidate,
    _score_debt_consolidation,
    _score_mortgage_candidate,
    _score_payday_loan_candidate,
    _score_personal_loan_candidate,
    _score_refinance_candidate,
)


# ── _score_auto_loan_candidate ───────────────────────────────────────────────


def test_auto_loan_vehicle_no_property_medium_income():
    score, reasons = _score_auto_loan_candidate(
        has_vehicle=True, has_property=False, income_estimate=45_000.0
    )
    assert score >= 0.65
    assert any("vehicle" in r.lower() for r in reasons)


def test_auto_loan_no_vehicle():
    score, _ = _score_auto_loan_candidate(
        has_vehicle=False, has_property=True, income_estimate=45_000.0
    )
    assert score < 0.65


# ── _score_payday_loan_candidate ─────────────────────────────────────────────


def test_payday_loan_high_distress_low_income():
    score, reasons = _score_payday_loan_candidate(
        financial_distress_score=0.7, has_property=False, income_estimate=20_000.0
    )
    assert score >= 0.65
    assert any("distress" in r.lower() for r in reasons)


def test_payday_loan_low_distress():
    score, _ = _score_payday_loan_candidate(
        financial_distress_score=0.2, has_property=False, income_estimate=20_000.0
    )
    assert score < 0.65


# ── _score_personal_loan_candidate ───────────────────────────────────────────


def test_personal_loan_employed():
    score, reasons = _score_personal_loan_candidate(is_employed=True, financial_distress_score=0.3)
    assert score >= 0.60
    assert any("employ" in r.lower() for r in reasons)


def test_personal_loan_unemployed_no_distress():
    score, _ = _score_personal_loan_candidate(is_employed=False, financial_distress_score=0.1)
    assert score < 0.60


# ── _score_mortgage_candidate ────────────────────────────────────────────────


def test_mortgage_candidate_property_record():
    score, reasons = _score_mortgage_candidate(
        has_property=True, income_estimate=80_000.0
    )
    assert score >= 0.70
    assert any("property" in r.lower() for r in reasons)


def test_mortgage_candidate_high_income_no_property():
    score, reasons = _score_mortgage_candidate(
        has_property=False, income_estimate=120_000.0
    )
    assert score >= 0.70
    assert any("income" in r.lower() for r in reasons)


def test_mortgage_candidate_no_signals():
    score, _ = _score_mortgage_candidate(has_property=False, income_estimate=15_000.0)
    assert score < 0.70


# ── _score_refinance_candidate ───────────────────────────────────────────────


def test_refinance_candidate_property_and_distress():
    score, reasons = _score_refinance_candidate(
        has_property=True, financial_distress_score=0.6
    )
    assert score >= 0.65
    assert any("distress" in r.lower() for r in reasons)


def test_refinance_candidate_no_property():
    score, _ = _score_refinance_candidate(has_property=False, financial_distress_score=0.8)
    assert score < 0.65


# ── _score_debt_consolidation ────────────────────────────────────────────────


def test_debt_consolidation_multiple_signals_and_distress():
    score, reasons = _score_debt_consolidation(
        financial_distress_score=0.7, criminal_count=1, has_vehicle=True, has_property=False
    )
    assert score >= 0.65
    assert any("distress" in r.lower() for r in reasons)


def test_debt_consolidation_no_distress():
    score, _ = _score_debt_consolidation(
        financial_distress_score=0.1, criminal_count=0, has_vehicle=False, has_property=False
    )
    assert score < 0.65
