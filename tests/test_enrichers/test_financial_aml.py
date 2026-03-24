"""Tests for modules/enrichers/financial_aml.py — pure logic, no DB required."""

from unittest.mock import MagicMock

import pytest

from modules.enrichers.financial_aml import (
    AMLResult,
    AMLScreener,
    AlternativeCreditScorer,
    CreditScoreResult,
    FraudRiskResult,
    FraudRiskScorer,
    _tier,
    _CREDIT_TIERS,
    _AML_TIERS,
    _FRAUD_TIERS,
    _SCORE_MIN,
    _SCORE_MAX,
)


# ─── _tier helper ─────────────────────────────────────────────────────────────


def test_tier_credit_excellent():
    assert _tier(820, _CREDIT_TIERS) == "excellent"


def test_tier_credit_good():
    assert _tier(760, _CREDIT_TIERS) == "good"


def test_tier_credit_fair():
    assert _tier(700, _CREDIT_TIERS) == "fair"


def test_tier_credit_poor():
    assert _tier(600, _CREDIT_TIERS) == "poor"


def test_tier_credit_very_poor():
    assert _tier(400, _CREDIT_TIERS) == "very_poor"


def test_tier_aml_low():
    assert _tier(0.10, _AML_TIERS) == "low"


def test_tier_aml_medium():
    assert _tier(0.30, _AML_TIERS) == "medium"


def test_tier_aml_high():
    assert _tier(0.60, _AML_TIERS) == "high"


def test_tier_aml_critical():
    assert _tier(0.80, _AML_TIERS) == "critical"


# ─── AlternativeCreditScorer ──────────────────────────────────────────────────


def _signals(**overrides):
    base = {
        "criminal_felony_count": 0,
        "criminal_misdemeanor_count": 0,
        "watchlist_hit_count": 0,
        "darkweb_mention_count": 0,
        "address_count": 1,
        "address_country_count": 1,
        "crypto_mixer_exposure": False,
        "crypto_total_volume_usd": 0,
        "wealth_band": "middle",
        "income_estimate_usd": None,
        "identifier_count": 5,
        "burner_flag": False,
        "pep_flag": False,
    }
    return {**base, **overrides}


def test_credit_score_clean_profile_is_high():
    scorer = AlternativeCreditScorer()
    result = scorer.score(_signals(wealth_band="high", income_estimate_usd=150_000))
    assert isinstance(result, CreditScoreResult)
    assert result.score >= 600
    assert result.risk_category in ("excellent", "good", "fair")


def test_credit_score_felony_reduces_score():
    scorer = AlternativeCreditScorer()
    clean = scorer.score(_signals())
    with_felony = scorer.score(_signals(criminal_felony_count=2))
    assert with_felony.score < clean.score


def test_credit_score_bounds():
    scorer = AlternativeCreditScorer()
    result = scorer.score(_signals(criminal_felony_count=100, darkweb_mention_count=100))
    assert _SCORE_MIN <= result.score <= _SCORE_MAX


def test_credit_score_confidence_interval_is_narrower_with_3_identifiers():
    scorer = AlternativeCreditScorer()
    narrow = scorer.score(_signals(identifier_count=3))
    wide = scorer.score(_signals(identifier_count=1))
    narrow_width = narrow.confidence_interval[1] - narrow.confidence_interval[0]
    wide_width = wide.confidence_interval[1] - wide.confidence_interval[0]
    assert narrow_width <= wide_width


def test_credit_score_component_breakdown_has_all_keys():
    scorer = AlternativeCreditScorer()
    result = scorer.score(_signals())
    for key in ("payment_behavior", "stability", "wealth", "utilization", "trajectory"):
        assert key in result.component_breakdown
        assert 0.0 <= result.component_breakdown[key] <= 1.0


def test_payment_behavior_pep_flag_penalizes():
    scorer = AlternativeCreditScorer()
    no_pep = scorer._payment_behavior(_signals())
    pep = scorer._payment_behavior(_signals(pep_flag=True))
    assert pep < no_pep


def test_stability_burner_penalizes():
    scorer = AlternativeCreditScorer()
    no_burner = scorer._stability(_signals())
    burner = scorer._stability(_signals(burner_flag=True))
    assert burner < no_burner


def test_stability_many_addresses_penalizes():
    scorer = AlternativeCreditScorer()
    stable = scorer._stability(_signals(address_count=1))
    unstable = scorer._stability(_signals(address_count=10))
    assert unstable < stable


def test_wealth_high_band_scores_higher():
    scorer = AlternativeCreditScorer()
    high = scorer._wealth(_signals(wealth_band="high"))
    low = scorer._wealth(_signals(wealth_band="low"))
    assert high > low


def test_wealth_mixer_penalizes():
    scorer = AlternativeCreditScorer()
    clean = scorer._wealth(_signals(wealth_band="high"))
    mixed = scorer._wealth(_signals(wealth_band="high", crypto_mixer_exposure=True))
    assert mixed < clean


def test_trajectory_large_clean_crypto_volume_boosts():
    scorer = AlternativeCreditScorer()
    base = scorer._trajectory(_signals())
    boosted = scorer._trajectory(_signals(crypto_total_volume_usd=200_000))
    assert boosted > base


# ─── AMLScreener ─────────────────────────────────────────────────────────────


def _make_watchlist(list_type: str, match_score: float = 0.9) -> MagicMock:
    m = MagicMock()
    m.list_type = list_type
    m.list_name = f"Test {list_type} list"
    m.match_score = match_score
    m.match_name = "John Doe"
    m.is_confirmed = True
    return m


def _make_darkweb(exposure_score: float = 0.5, severity: str = "high") -> MagicMock:
    m = MagicMock()
    m.exposure_score = exposure_score
    m.severity = severity
    m.mention_context = "test mention"
    return m


def _make_crypto(mixer_exposure: bool = False, risk_score: float = 0.3, total_volume_usd: float = 0.0) -> MagicMock:
    m = MagicMock()
    m.mixer_exposure = mixer_exposure
    m.risk_score = risk_score
    m.total_volume_usd = total_volume_usd
    return m


def test_aml_clean_profile_is_low_risk():
    screener = AMLScreener()
    result = screener.screen([], [], [])
    assert result.risk_score == 0.0
    assert result.risk_tier == "low"
    assert not result.is_pep
    assert result.sanctions_hits == []


def test_aml_pep_flag_and_risk():
    screener = AMLScreener()
    result = screener.screen([_make_watchlist("pep")], [], [])
    assert result.is_pep is True
    assert result.risk_score >= 0.40
    assert result.risk_tier in ("medium", "high", "critical")


def test_aml_sanctions_hit_sets_critical_risk():
    screener = AMLScreener()
    result = screener.screen([_make_watchlist("sanctions")], [], [])
    assert result.risk_score >= 0.90
    assert result.risk_tier == "critical"
    assert len(result.sanctions_hits) == 1


def test_aml_fugitive_adds_sanctions_hit():
    screener = AMLScreener()
    result = screener.screen([_make_watchlist("fugitive")], [], [])
    assert result.risk_score >= 0.70
    assert len(result.sanctions_hits) == 1


def test_aml_darkweb_exposure_raises_risk():
    screener = AMLScreener()
    result = screener.screen([], [_make_darkweb(0.8)], [])
    assert result.risk_score > 0.0
    assert result.darkweb_mention_count == 1


def test_aml_crypto_mixer_raises_risk():
    screener = AMLScreener()
    result = screener.screen([], [], [_make_crypto(mixer_exposure=True)])
    assert result.risk_score >= 0.65


def test_aml_high_risk_crypto_raises_risk():
    screener = AMLScreener()
    result = screener.screen([], [], [_make_crypto(risk_score=0.9)])
    assert result.risk_score > 0.0


def test_aml_result_capped_at_one():
    screener = AMLScreener()
    watchlists = [_make_watchlist("sanctions"), _make_watchlist("terrorist")]
    result = screener.screen(watchlists, [_make_darkweb(1.0)], [_make_crypto(mixer_exposure=True)])
    assert result.risk_score <= 1.0


# ─── FraudRiskScorer ──────────────────────────────────────────────────────────


def _make_address(country_code: str = "US", updated_at=None) -> MagicMock:
    m = MagicMock()
    m.country_code = country_code
    m.updated_at = updated_at
    return m


def _make_identifier(type: str = "email", confidence: float = 0.9, updated_at=None) -> MagicMock:
    m = MagicMock()
    m.type = type
    m.confidence = confidence
    m.updated_at = updated_at
    return m


def _make_criminal(charge: str = "fraud", offense_level: str = "felony", disposition: str = "guilty") -> MagicMock:
    m = MagicMock()
    m.charge = charge
    m.offense_level = offense_level
    m.disposition = disposition
    return m


def test_fraud_clean_is_zero():
    scorer = FraudRiskScorer()
    result = scorer.score([], [], [], [], [])
    assert result.fraud_score == 0.0
    assert result.tier == "low"
    assert result.fraud_indicators == []


def test_fraud_high_address_velocity():
    scorer = FraudRiskScorer()
    addresses = [_make_address() for _ in range(9)]
    result = scorer.score(addresses, [], [], [], [])
    assert result.fraud_score >= 0.20
    assert any("high address velocity" in ind for ind in result.fraud_indicators)


def test_fraud_moderate_address_velocity():
    scorer = FraudRiskScorer()
    addresses = [_make_address() for _ in range(6)]
    result = scorer.score(addresses, [], [], [], [])
    assert result.fraud_score >= 0.10
    assert any("elevated address velocity" in ind for ind in result.fraud_indicators)


def test_fraud_multi_country_raises_score():
    scorer = FraudRiskScorer()
    addresses = [_make_address("US"), _make_address("UK"), _make_address("DE"), _make_address("FR")]
    result = scorer.score(addresses, [], [], [], [])
    assert any("multi-country" in ind for ind in result.fraud_indicators)


def test_fraud_low_confidence_identifiers():
    scorer = FraudRiskScorer()
    ids = [_make_identifier(confidence=0.3), _make_identifier(confidence=0.4)]
    result = scorer.score([], ids, [], [], [])
    assert any("low-confidence" in ind for ind in result.fraud_indicators)


def test_fraud_duplicate_identifier_types():
    scorer = FraudRiskScorer()
    ids = [_make_identifier(type="email"), _make_identifier(type="email")]
    result = scorer.score([], ids, [], [], [])
    assert any("duplicate identifier" in ind for ind in result.fraud_indicators)


def test_fraud_high_severity_darkweb():
    scorer = FraudRiskScorer()
    dw = [_make_darkweb(severity="critical")]
    result = scorer.score([], [], dw, [], [])
    assert any("high-severity darkweb" in ind for ind in result.fraud_indicators)


def test_fraud_low_severity_darkweb():
    scorer = FraudRiskScorer()
    dw = [_make_darkweb(severity="low")]
    result = scorer.score([], [], dw, [], [])
    assert any("darkweb mentions" in ind for ind in result.fraud_indicators)


def test_fraud_fraud_criminal_charge():
    scorer = FraudRiskScorer()
    result = scorer.score([], [], [], [_make_criminal(charge="wire fraud")], [])
    assert any("fraud-related criminal" in ind for ind in result.fraud_indicators)


def test_fraud_mixer_wallet():
    scorer = FraudRiskScorer()
    result = scorer.score([], [], [], [], [_make_crypto(mixer_exposure=True)])
    assert any("mixer exposure" in ind for ind in result.fraud_indicators)


def test_fraud_score_capped_at_one():
    scorer = FraudRiskScorer()
    addresses = [_make_address() for _ in range(12)]
    ids = [_make_identifier(confidence=0.1) for _ in range(10)] + [_make_identifier(type="ssn"), _make_identifier(type="ssn")]
    darkweb = [_make_darkweb(severity="critical") for _ in range(10)]
    criminals = [_make_criminal(charge="wire fraud") for _ in range(5)]
    crypto = [_make_crypto(mixer_exposure=True) for _ in range(3)]
    result = scorer.score(addresses, ids, darkweb, criminals, crypto)
    assert result.fraud_score <= 1.0
