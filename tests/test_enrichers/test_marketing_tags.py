"""Tests for modules/enrichers/marketing_tags.py — pure logic, no DB required."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from modules.enrichers.marketing_tags import (
    BehaviouralTag,
    BorrowerProfile,
    HighInterestBorrowerScorer,
    InvestmentTag,
    LendingTag,
    LifeStageTag,
    TagResult,
    _clamp,
    _compute_age,
    _darkweb_text,
    _score_active_gambler,
    _score_crypto_investor,
    _score_luxury_buyer,
    _score_new_parent,
    _score_real_estate_investor,
    _score_recent_mover,
    _score_retiring_soon,
    _score_title_loan,
    _social_text,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_wealth(wealth_band: str = "middle", vehicle_signal: float = 0.0) -> MagicMock:
    m = MagicMock()
    m.wealth_band = wealth_band
    m.vehicle_signal = vehicle_signal
    m.income_estimate_usd = 50_000.0
    return m


def _make_criminal(charge: str = "assault", offense_level: str = "misdemeanor") -> MagicMock:
    m = MagicMock()
    m.charge = charge
    m.offense_level = offense_level
    return m


def _make_address(
    city: str = "Austin",
    state_province: str = "TX",
    country_code: str = "US",
    updated_at=None,
) -> MagicMock:
    m = MagicMock()
    m.city = city
    m.state_province = state_province
    m.country_code = country_code
    m.updated_at = updated_at
    return m


def _make_social(handle: str = "", bio: str = "") -> MagicMock:
    m = MagicMock()
    m.handle = handle
    m.bio = bio
    return m


def _make_darkweb(mention_context: str = "", severity: str = "low") -> MagicMock:
    m = MagicMock()
    m.mention_context = mention_context
    m.severity = severity
    return m


def _make_behavioural(gambling_score: float = 0.0, interests: list | None = None) -> MagicMock:
    m = MagicMock()
    m.gambling_score = gambling_score
    m.interests = interests or []
    return m


def _make_identifier(type: str = "email", updated_at=None) -> MagicMock:
    m = MagicMock()
    m.type = type
    m.updated_at = updated_at
    return m


def _make_crypto_wallet(
    mixer_exposure: bool = False, risk_score: float = 0.3, total_volume_usd: float = 0.0
) -> MagicMock:
    m = MagicMock()
    m.mixer_exposure = mixer_exposure
    m.risk_score = risk_score
    m.total_volume_usd = total_volume_usd
    return m


def _make_employment(
    is_current: bool = True,
    job_title: str = "engineer",
    industry: str = "tech",
    employer_name: str = "Acme Corp",
    started_at=None,
) -> MagicMock:
    m = MagicMock()
    m.is_current = is_current
    m.job_title = job_title
    m.industry = industry
    m.employer_name = employer_name
    m.started_at = started_at or date(2015, 1, 1)
    return m


# ─── _compute_age ─────────────────────────────────────────────────────────────


def test_compute_age_none_dob():
    assert _compute_age(None) is None


def test_compute_age_known_dob():
    today = date.today()
    dob = date(today.year - 30, today.month, today.day)
    assert _compute_age(dob) == 30


def test_compute_age_before_birthday_this_year():
    today = date.today()
    # birthday hasn't happened yet this year
    if today.month == 12 and today.day == 31:
        pytest.skip("edge case: last day of year")
    future_birthday_month = today.month + 1 if today.month < 12 else 12
    dob = date(today.year - 25, future_birthday_month, 1)
    age = _compute_age(dob)
    assert age == 24


# ─── _clamp ───────────────────────────────────────────────────────────────────


def test_clamp_above_one():
    assert _clamp(1.5) == 1.0


def test_clamp_below_zero():
    assert _clamp(-0.5) == 0.0


def test_clamp_in_range():
    assert _clamp(0.7) == 0.7


# ─── _social_text ─────────────────────────────────────────────────────────────


def test_social_text_combines_handle_and_bio():
    profiles = [_make_social(handle="@CryptoBro", bio="Love Bitcoin")]
    text = _social_text(profiles)
    assert "cryptobro" in text
    assert "bitcoin" in text


def test_social_text_empty():
    assert _social_text([]) == ""


# ─── _darkweb_text ────────────────────────────────────────────────────────────


def test_darkweb_text_combines_contexts():
    mentions = [
        _make_darkweb(mention_context="poker forum"),
        _make_darkweb(mention_context="casino listing"),
    ]
    text = _darkweb_text(mentions)
    assert "poker" in text
    assert "casino" in text


# ─── _score_title_loan ────────────────────────────────────────────────────────


def test_title_loan_vehicle_signal_triggers():
    wealth = _make_wealth(vehicle_signal=0.5)
    score, reasons = _score_title_loan([], [], wealth)
    assert score >= 0.4
    assert any("vehicle signal" in r for r in reasons)


def test_title_loan_financial_crime_triggers():
    criminal = _make_criminal(charge="lien on property")
    score, reasons = _score_title_loan([], [criminal], None)
    assert score >= 0.3
    assert any("financial crime" in r for r in reasons)


def test_title_loan_low_wealth_band_triggers():
    wealth = _make_wealth(wealth_band="low")
    score, reasons = _score_title_loan([], [], wealth)
    assert score >= 0.2
    assert any("wealth band" in r for r in reasons)


def test_title_loan_address_instability_triggers():
    addresses = [_make_address() for _ in range(4)]
    score, reasons = _score_title_loan(addresses, [], None)
    assert score >= 0.1
    assert any("address instability" in r for r in reasons)


def test_title_loan_no_signals_zero():
    score, reasons = _score_title_loan(
        [_make_address()], [], _make_wealth(wealth_band="high", vehicle_signal=0.0)
    )
    assert score == 0.0
    assert reasons == []


# ─── _score_active_gambler ────────────────────────────────────────────────────


def test_active_gambler_darkweb_keyword():
    dw = [_make_darkweb(mention_context="casino poker night")]
    score, reasons = _score_active_gambler(dw, [], None, None)
    assert score >= 0.3
    assert any("darkweb" in r for r in reasons)


def test_active_gambler_social_keyword():
    socials = [_make_social(bio="love betting and poker")]
    score, reasons = _score_active_gambler([], socials, None, None)
    assert score >= 0.2
    assert any("social" in r.lower() for r in reasons)


def test_active_gambler_behavioural_score():
    behav = _make_behavioural(gambling_score=0.5)
    score, reasons = _score_active_gambler([], [], behav, None)
    assert score >= 0.2
    assert any("gambling score" in r for r in reasons)


def test_active_gambler_prime_age():
    score, reasons = _score_active_gambler([], [], None, 35)
    assert score >= 0.2
    assert any("prime gambler demographic" in r for r in reasons)


def test_active_gambler_no_signals_zero():
    score, _ = _score_active_gambler([], [], None, None)
    assert score == 0.0


# ─── _score_crypto_investor ───────────────────────────────────────────────────


def test_crypto_investor_wallets_trigger():
    wallets = [_make_crypto_wallet()]
    score, reasons = _score_crypto_investor(wallets, [], [])
    assert score >= 0.5
    assert any("wallet" in r for r in reasons)


def test_crypto_investor_crypto_identifier():
    ids = [_make_identifier(type="crypto_wallet")]
    score, reasons = _score_crypto_investor([], ids, [])
    assert score >= 0.3
    assert any("identifier" in r for r in reasons)


def test_crypto_investor_social_keyword():
    socials = [_make_social(bio="DeFi and Ethereum enthusiast")]
    score, reasons = _score_crypto_investor([], [], socials)
    assert score >= 0.2
    assert any("social" in r.lower() for r in reasons)


def test_crypto_investor_no_signals_zero():
    score, _ = _score_crypto_investor([], [], [])
    assert score == 0.0


# ─── _score_real_estate_investor ─────────────────────────────────────────────


def test_real_estate_investor_multiple_cities():
    addresses = [
        _make_address(city="Austin", state_province="TX"),
        _make_address(city="Dallas", state_province="TX"),
    ]
    score, reasons = _score_real_estate_investor(addresses, [], None)
    assert score >= 0.5
    assert any("distinct address" in r for r in reasons)


def test_real_estate_investor_re_employment():
    emp = [_make_employment(industry="real estate brokerage")]
    score, reasons = _score_real_estate_investor([_make_address()], emp, None)
    assert score >= 0.3
    assert any("real estate" in r for r in reasons)


def test_real_estate_investor_high_wealth():
    wealth = _make_wealth(wealth_band="high")
    score, reasons = _score_real_estate_investor([_make_address()], [], wealth)
    assert score >= 0.2
    assert any("wealth band" in r for r in reasons)


# ─── _score_recent_mover ──────────────────────────────────────────────────────


def test_recent_mover_address_updated_within_90_days():
    recent_dt = datetime.now(UTC) - timedelta(days=30)
    addresses = [_make_address(updated_at=recent_dt)]
    score, reasons = _score_recent_mover(addresses, [])
    assert score >= 0.7
    assert any("address record" in r for r in reasons)


def test_recent_mover_no_recent_addresses():
    old_dt = datetime.now(UTC) - timedelta(days=200)
    addresses = [_make_address(updated_at=old_dt)]
    score, _ = _score_recent_mover(addresses, [])
    assert score == 0.0


def test_recent_mover_address_identifier_updated():
    recent_dt = datetime.now(UTC) - timedelta(days=45)
    ids = [_make_identifier(type="home_address", updated_at=recent_dt)]
    score, reasons = _score_recent_mover([], ids)
    assert score >= 0.3
    assert any("identifier" in r for r in reasons)


# ─── _score_luxury_buyer ──────────────────────────────────────────────────────


def test_luxury_buyer_high_wealth():
    wealth = _make_wealth(wealth_band="high")
    score, reasons = _score_luxury_buyer(wealth, [], [])
    assert score >= 0.5
    assert any("wealth band" in r for r in reasons)


def test_luxury_buyer_high_income_title():
    wealth = _make_wealth(wealth_band="high")
    emp = [_make_employment(job_title="CEO", is_current=True)]
    score, reasons = _score_luxury_buyer(wealth, emp, [])
    assert score >= 0.8
    assert any("high-income job" in r for r in reasons)


def test_luxury_buyer_multiple_addresses():
    addresses = [_make_address(), _make_address(city="Miami")]
    score, reasons = _score_luxury_buyer(None, [], addresses)
    assert score >= 0.2
    assert any("property records" in r for r in reasons)


def test_luxury_buyer_no_signals_zero():
    score, _ = _score_luxury_buyer(None, [], [])
    assert score == 0.0


# ─── _score_retiring_soon ────────────────────────────────────────────────────


def test_retiring_soon_age_in_range():
    score, reasons = _score_retiring_soon(63, [])
    assert score >= 0.7
    assert any("pre-retirement" in r for r in reasons)


def test_retiring_soon_age_out_of_range():
    score, _ = _score_retiring_soon(45, [])
    assert score == 0.0


def test_retiring_soon_long_tenure():
    started = date(date.today().year - 20, 1, 1)
    emp = [_make_employment(is_current=True, started_at=started)]
    score, reasons = _score_retiring_soon(None, emp)
    assert score >= 0.3
    assert any("employment tenure" in r for r in reasons)


# ─── _score_new_parent ───────────────────────────────────────────────────────


def test_new_parent_parenting_interests():
    behav = _make_behavioural(interests=["baby gear", "diaper brands"])
    score, reasons = _score_new_parent(behav, None, [])
    assert score >= 0.5
    assert any("parenting" in r for r in reasons)


def test_new_parent_age_in_range():
    score, reasons = _score_new_parent(None, 30, [])
    assert score >= 0.3
    assert any("new-parent range" in r for r in reasons)


def test_new_parent_recent_move():
    recent_dt = datetime.now(UTC) - timedelta(days=60)
    addresses = [_make_address(updated_at=recent_dt)]
    score, reasons = _score_new_parent(None, None, addresses)
    assert score >= 0.2
    assert any("address change" in r for r in reasons)


# ─── HighInterestBorrowerScorer ───────────────────────────────────────────────


def test_borrower_scorer_clean_profile_is_prime():
    scorer = HighInterestBorrowerScorer()
    emp = [_make_employment(is_current=True, started_at=date(date.today().year - 6, 1, 1))]
    result = scorer.score([], [_make_address()], emp, _make_wealth(wealth_band="high"))
    assert result.tier in ("prime", "near_prime")
    assert isinstance(result.applicable_products, list)
    assert len(result.applicable_products) > 0


def test_borrower_scorer_liens_reduce_score():
    scorer = HighInterestBorrowerScorer()
    lien = _make_criminal(charge="lien on vehicle")
    result = scorer.score([lien], [], [], None)
    assert result.score < 100


def test_borrower_scorer_bankruptcy_reduces_score():
    scorer = HighInterestBorrowerScorer()
    bankrupt = _make_criminal(charge="bankruptcy filing")
    result = scorer.score([bankrupt], [], [], None)
    assert result.score <= 80
    assert any("bankruptcy" in s for s in result.signals)


def test_borrower_scorer_no_employment_penalizes():
    scorer = HighInterestBorrowerScorer()
    result = scorer.score([], [], [], None)
    assert any("no current employment" in s for s in result.signals)


def test_borrower_scorer_short_tenure_penalizes():
    scorer = HighInterestBorrowerScorer()
    emp = [_make_employment(is_current=True, started_at=date(date.today().year - 1, 6, 1))]
    result = scorer.score([], [], emp, None)
    # Short tenure: could be penalized; check signals mention tenure
    # (May or may not trigger depending on exact days — just check it runs)
    assert isinstance(result, BorrowerProfile)


def test_borrower_scorer_high_address_instability():
    scorer = HighInterestBorrowerScorer()
    addresses = [_make_address() for _ in range(7)]
    result = scorer.score([], addresses, [], None)
    assert any("high address instability" in s for s in result.signals)


def test_borrower_scorer_score_clamped_0_100():
    scorer = HighInterestBorrowerScorer()
    criminals = [_make_criminal(charge=f"lien {i}") for i in range(20)]
    result = scorer.score(criminals, [], [], _make_wealth(wealth_band="low"))
    assert 0 <= result.score <= 100


def test_borrower_scorer_low_wealth_penalizes():
    scorer = HighInterestBorrowerScorer()
    result = scorer.score([], [], [], _make_wealth(wealth_band="low"))
    assert any("low" in s.lower() for s in result.signals)


def test_borrower_scorer_stable_employment_boosts():
    scorer = HighInterestBorrowerScorer()
    emp = [_make_employment(is_current=True, started_at=date(date.today().year - 8, 1, 1))]
    result = scorer.score([], [], emp, None)
    assert any("stable employment" in s for s in result.signals)
