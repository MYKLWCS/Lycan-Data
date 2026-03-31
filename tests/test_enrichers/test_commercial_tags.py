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
    score, reasons = _score_mortgage_candidate(has_property=True, income_estimate=80_000.0)
    assert score >= 0.70
    assert any("property" in r.lower() for r in reasons)


def test_mortgage_candidate_high_income_no_property():
    score, reasons = _score_mortgage_candidate(has_property=False, income_estimate=120_000.0)
    assert score >= 0.70
    assert any("income" in r.lower() for r in reasons)


def test_mortgage_candidate_no_signals():
    score, _ = _score_mortgage_candidate(has_property=False, income_estimate=15_000.0)
    assert score < 0.70


# ── _score_refinance_candidate ───────────────────────────────────────────────


def test_refinance_candidate_property_and_distress():
    score, reasons = _score_refinance_candidate(has_property=True, financial_distress_score=0.6)
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


# ── Task 6: PersonSignals dataclass ──────────────────────────────────────────

from modules.enrichers.commercial_tagger import PersonSignals


def test_person_signals_is_dataclass():
    import dataclasses

    assert dataclasses.is_dataclass(PersonSignals)


def test_person_signals_fields():
    import uuid

    s = PersonSignals(
        person_id=uuid.uuid4(),
        has_vehicle=True,
        has_property=False,
        financial_distress_score=0.4,
        gambling_score=0.1,
        income_estimate=55_000.0,
        net_worth_estimate=None,
        is_employed=True,
        age=34,
        criminal_count=0,
        has_investment_signals=False,
    )
    assert s.has_vehicle is True
    assert s.age == 34
    assert s.income_estimate == 55_000.0


# ── Task 7: CommercialTagsEngine ──────────────────────────────────────────────

import uuid

from modules.enrichers.commercial_tagger import CommercialTagsEngine
from modules.enrichers.marketing_tags import BankingTag, InsuranceTag, LendingTag, WealthTag


def _make_signals(**overrides) -> PersonSignals:
    defaults = {
        "person_id": uuid.uuid4(),
        "has_vehicle": False,
        "has_property": False,
        "financial_distress_score": 0.0,
        "gambling_score": 0.0,
        "income_estimate": None,
        "net_worth_estimate": None,
        "is_employed": False,
        "age": None,
        "criminal_count": 0,
        "has_investment_signals": False,
    }
    defaults.update(overrides)
    return PersonSignals(**defaults)


def test_commercial_engine_insurance_auto_tag():
    engine = CommercialTagsEngine()
    signals = _make_signals(has_vehicle=True)
    results = engine.tag_person(signals)
    tags = [r.tag for r in results]
    assert InsuranceTag.INSURANCE_AUTO in tags


def test_commercial_engine_banking_basic_tag():
    engine = CommercialTagsEngine()
    signals = _make_signals(is_employed=True, age=30)
    results = engine.tag_person(signals)
    tags = [r.tag for r in results]
    assert BankingTag.BANKING_BASIC in tags


def test_commercial_engine_high_net_worth_tag():
    engine = CommercialTagsEngine()
    signals = _make_signals(
        net_worth_estimate=1_500_000.0,
        has_property=True,
        has_investment_signals=True,
    )
    results = engine.tag_person(signals)
    tags = [r.tag for r in results]
    assert WealthTag.HIGH_NET_WORTH in tags


def test_commercial_engine_returns_tag_results_with_reasoning():
    engine = CommercialTagsEngine()
    signals = _make_signals(has_vehicle=True)
    results = engine.tag_person(signals)
    for r in results:
        assert isinstance(r.reasoning, list)
        assert len(r.reasoning) > 0
        assert 0.0 <= r.confidence <= 1.0


def test_commercial_engine_no_signals_returns_empty():
    engine = CommercialTagsEngine()
    signals = _make_signals()  # all defaults — nothing fires
    results = engine.tag_person(signals)
    assert results == []


# ── Task 8: CommercialTaggerDaemon ────────────────────────────────────────────

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from modules.enrichers.commercial_tagger import CommercialTaggerDaemon


def test_daemon_instantiates():
    daemon = CommercialTaggerDaemon()
    assert not daemon._running


async def test_daemon_stop_sets_running_false():
    daemon = CommercialTaggerDaemon()
    daemon._running = True
    daemon.stop()
    assert not daemon._running


async def test_daemon_run_batch_calls_engine(monkeypatch):
    """_run_batch with no persons in DB completes without error."""
    daemon = CommercialTaggerDaemon()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "modules.enrichers.commercial_tagger.AsyncSessionLocal",
        return_value=mock_ctx,
    ):
        await daemon._run_batch()  # must not raise


import uuid as _uuid_mod
from datetime import UTC

import pytest


@pytest.mark.asyncio
async def test_assemble_person_signals_all_none():
    """assemble_person_signals with no person/wealth/behavioural rows → defaults (lines 70-136)."""
    from modules.enrichers.commercial_tagger import assemble_person_signals

    session = AsyncMock()
    pid = _uuid_mod.uuid4()

    call_count = [0]

    def _empty_scalars():
        s = MagicMock()
        s.first.return_value = None
        s.all.return_value = []
        return s

    async def fake_execute(stmt):
        r = MagicMock()
        call_count[0]
        call_count[0] += 1
        r.scalars.return_value = _empty_scalars()
        r.scalar.return_value = 0
        return r

    session.execute = fake_execute

    signals = await assemble_person_signals(pid, session)
    assert signals.is_employed is False
    assert signals.criminal_count == 0
    assert signals.has_vehicle is False
    assert signals.income_estimate is None


@pytest.mark.asyncio
async def test_upsert_commercial_tags_new_row():
    """_upsert_commercial_tags inserts a new MarketingTag when no existing row (line 346-356)."""
    from datetime import datetime, timezone

    from modules.enrichers.commercial_tagger import _upsert_commercial_tags
    from modules.enrichers.marketing_tags import TagResult

    pid = _uuid_mod.uuid4()
    tag_result = TagResult(
        tag="insurance_auto",
        confidence=0.9,
        reasoning=["has vehicle"],
        scored_at=datetime.now(UTC),
    )

    session = AsyncMock()
    added = []
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))

    # Query returns no existing row
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    await _upsert_commercial_tags(pid, [tag_result], session)
    assert len(added) == 1
    assert added[0].tag == "insurance_auto"


@pytest.mark.asyncio
async def test_upsert_commercial_tags_existing_row():
    """_upsert_commercial_tags updates confidence on existing MarketingTag (line 341-345)."""
    from datetime import datetime, timezone

    from modules.enrichers.commercial_tagger import _upsert_commercial_tags
    from modules.enrichers.marketing_tags import TagResult

    pid = _uuid_mod.uuid4()
    tag_result = TagResult(
        tag="insurance_auto",
        confidence=0.85,
        reasoning=["has vehicle"],
        scored_at=datetime.now(UTC),
    )

    existing_row = MagicMock()
    existing_row.tag = "insurance_auto"

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = existing_row
    session.execute = AsyncMock(return_value=mock_result)

    await _upsert_commercial_tags(pid, [tag_result], session)
    assert existing_row.confidence == 0.85


@pytest.mark.asyncio
async def test_daemon_run_batch_with_persons_exception_caught():
    """Daemon processes persons; per-person exception is caught (lines 304-317)."""
    daemon = CommercialTaggerDaemon()

    person = MagicMock()
    person.id = _uuid_mod.uuid4()

    # Outer session query
    outer_session = AsyncMock()
    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [person]
    outer_session.execute = AsyncMock(return_value=mock_persons_result)

    outer_ctx = AsyncMock()
    outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
    outer_ctx.__aexit__ = AsyncMock(return_value=False)

    # Inner per-person session raises
    inner_ctx = AsyncMock()
    inner_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("db error"))
    inner_ctx.__aexit__ = AsyncMock(return_value=False)

    call_count = [0]

    def session_factory():
        c = call_count[0]
        call_count[0] += 1
        return outer_ctx if c == 0 else inner_ctx

    with patch(
        "modules.enrichers.commercial_tagger.AsyncSessionLocal", side_effect=session_factory
    ):
        await daemon._run_batch()  # should not raise


@pytest.mark.asyncio
async def test_daemon_run_batch_with_persons_happy_path():
    """Daemon processes persons; happy path runs assemble → tag → upsert → commit (lines 309-312)."""
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon, PersonSignals

    daemon = CommercialTaggerDaemon()

    person = MagicMock()
    person.id = _uuid_mod.uuid4()

    # Outer session returns one person
    outer_session = AsyncMock()
    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [person]
    outer_session.execute = AsyncMock(return_value=mock_persons_result)

    outer_ctx = AsyncMock()
    outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
    outer_ctx.__aexit__ = AsyncMock(return_value=False)

    # Inner per-person session succeeds
    inner_session = AsyncMock()

    # assemble_person_signals will call execute multiple times
    def _empty_r():
        r = MagicMock()
        r.scalars.return_value.first.return_value = None
        r.scalars.return_value.all.return_value = []
        r.scalar.return_value = 0
        return r

    inner_session.execute = AsyncMock(return_value=_empty_r())
    inner_session.add = MagicMock()
    inner_session.commit = AsyncMock()

    inner_ctx = AsyncMock()
    inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
    inner_ctx.__aexit__ = AsyncMock(return_value=False)

    call_count = [0]

    def session_factory():
        c = call_count[0]
        call_count[0] += 1
        return outer_ctx if c == 0 else inner_ctx

    with patch(
        "modules.enrichers.commercial_tagger.AsyncSessionLocal", side_effect=session_factory
    ):
        await daemon._run_batch()  # should complete without error

    assert inner_session.commit.called
