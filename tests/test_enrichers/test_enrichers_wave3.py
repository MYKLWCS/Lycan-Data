"""Wave 3 enricher tests — DB orchestrator coverage for financial_aml and marketing_tags.

Targets:
  modules/enrichers/financial_aml.py  — FinancialIntelligenceEngine.score_person()
    lines 310-368: DB queries (darkweb, crypto, addresses, identifiers, criminals, wealth, burner)
    lines 389-391: signals dict (identifier_count, burner_flag, pep_flag)
    lines 433-502: WealthAssessment upsert, Person update, event bus publish

  modules/enrichers/marketing_tags.py
    lines 467-469: HighInterestBorrowerScorer moderate address instability elif branch
    lines 529-665: MarketingTagsEngine.tag_person() DB orchestrator, all scorers, tag filtering
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.financial_aml import FinancialIntelligenceEngine, FinancialProfile
from modules.enrichers.marketing_tags import (
    BorrowerProfile,
    HighInterestBorrowerScorer,
    MarketingTagsEngine,
    TagResult,
)


# ─── Shared mock-building helpers ────────────────────────────────────────────


def _exec_all(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = list(items)
    return r


def _exec_first(item) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.first.return_value = item
    return r


def _make_session(execute_side_effects: list, get_return=None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effects)
    session.get = AsyncMock(return_value=get_return)
    return session


def _make_marketing_session(execute_side_effects: list) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effects)
    return session


# ─── financial_aml row factories ─────────────────────────────────────────────


def _watchlist_row(list_type: str = "pep") -> MagicMock:
    m = MagicMock()
    m.list_type = list_type
    m.list_name = f"Test {list_type}"
    m.match_score = 0.95
    m.match_name = "Test Person"
    m.is_confirmed = True
    return m


def _darkweb_row(exposure_score: float = 0.3, severity: str = "low") -> MagicMock:
    m = MagicMock()
    m.exposure_score = exposure_score
    m.severity = severity
    m.mention_context = "test context"
    return m


def _crypto_row(mixer_exposure: bool = False, risk_score: float = 0.2, total_volume_usd: float = 0.0) -> MagicMock:
    m = MagicMock()
    m.mixer_exposure = mixer_exposure
    m.risk_score = risk_score
    m.total_volume_usd = total_volume_usd
    return m


def _address_row(country_code: str = "US", city: str = "Austin") -> MagicMock:
    m = MagicMock()
    m.country_code = country_code
    m.city = city
    m.state_province = "TX"
    m.updated_at = datetime.now(UTC)
    return m


def _identifier_row(confidence: float = 0.9) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.type = "email"
    m.confidence = confidence
    m.updated_at = None
    return m


def _criminal_row(offense_level: str = "misdemeanor", charge: str = "disorderly conduct", disposition: str = "acquitted") -> MagicMock:
    m = MagicMock()
    m.offense_level = offense_level
    m.charge = charge
    m.disposition = disposition
    return m


def _burner_row(burner_score: float = 0.6) -> MagicMock:
    m = MagicMock()
    m.burner_score = burner_score
    return m


def _person_row() -> MagicMock:
    m = MagicMock()
    m.default_risk_score = 0.0
    m.darkweb_exposure = 0.0
    m.behavioural_risk = 0.0
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# Task 1 — FinancialIntelligenceEngine.score_person() DB orchestrator
# ═══════════════════════════════════════════════════════════════════════════════


class TestFinancialEngineScorePerson:

    @pytest.mark.asyncio
    async def test_score_person_no_existing_wealth_creates_new_record(self):
        person_id = str(uuid.uuid4())
        person_mock = _person_row()
        ident = _identifier_row(confidence=0.95)

        execute_results = [
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([_address_row()]),
            _exec_all([ident]),
            _exec_all([]),
            _exec_first(None),
            _exec_all([]),
        ]

        session = _make_session(execute_results, get_return=person_mock)
        engine = FinancialIntelligenceEngine()

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            profile = await engine.score_person(person_id, session)

        assert isinstance(profile, FinancialProfile)
        assert profile.person_id == person_id
        assert 300 <= profile.credit.score <= 850
        assert profile.aml.is_pep is False

    @pytest.mark.asyncio
    async def test_score_person_existing_wealth_updates_in_place(self):
        person_id = str(uuid.uuid4())
        ident = _identifier_row()
        wealth_mock = MagicMock()
        wealth_mock.wealth_band = "middle"
        wealth_mock.income_estimate_usd = 40_000.0
        wealth_mock.crypto_signal = 0.0
        wealth_mock.confidence = 0.5
        wealth_mock.assessed_at = datetime.now(UTC)

        execute_results = [
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([_address_row()]),
            _exec_all([ident]),
            _exec_all([]),
            _exec_first(wealth_mock),
            _exec_all([]),
        ]

        session = _make_session(execute_results, get_return=_person_row())
        engine = FinancialIntelligenceEngine()

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            profile = await engine.score_person(person_id, session)

        assert session.add.call_count == 1
        assert wealth_mock.wealth_band == "middle"
        assert isinstance(profile, FinancialProfile)

    @pytest.mark.asyncio
    async def test_score_person_pep_flag_and_burner_flag(self):
        person_id = str(uuid.uuid4())
        ident1 = _identifier_row(confidence=0.8)
        ident2 = _identifier_row(confidence=0.3)
        burner = _burner_row(burner_score=0.55)
        pep_hit = _watchlist_row(list_type="pep")
        felony = _criminal_row(offense_level="felony", charge="fraud", disposition="guilty")

        execute_results = [
            _exec_all([pep_hit]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([_address_row(), _address_row("GB", "London")]),
            _exec_all([ident1, ident2]),
            _exec_all([felony]),
            _exec_first(None),
            _exec_all([burner]),
        ]

        session = _make_session(execute_results, get_return=_person_row())
        engine = FinancialIntelligenceEngine()

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            profile = await engine.score_person(person_id, session)

        assert profile.aml.is_pep is True
        assert profile.aml.risk_score >= 0.40
        assert 300 <= profile.credit.score <= 850

    @pytest.mark.asyncio
    async def test_score_person_crypto_and_darkweb_signals(self):
        person_id = str(uuid.uuid4())
        crypto = _crypto_row(mixer_exposure=True, risk_score=0.8, total_volume_usd=500_000.0)
        darkweb = _darkweb_row(exposure_score=0.7, severity="high")

        execute_results = [
            _exec_all([]),
            _exec_all([darkweb]),
            _exec_all([crypto]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
        ]

        session = _make_session(execute_results, get_return=_person_row())
        engine = FinancialIntelligenceEngine()

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            profile = await engine.score_person(person_id, session)

        assert isinstance(profile, FinancialProfile)
        assert profile.aml.darkweb_mention_count == 1
        assert profile.aml.risk_score >= 0.65

    @pytest.mark.asyncio
    async def test_score_person_event_bus_exception_is_swallowed(self):
        person_id = str(uuid.uuid4())

        execute_results = [
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
        ]

        session = _make_session(execute_results, get_return=None)
        engine = FinancialIntelligenceEngine()

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=Exception("dragonfly down"))
            profile = await engine.score_person(person_id, session)

        assert isinstance(profile, FinancialProfile)

    @pytest.mark.asyncio
    async def test_score_person_identifier_empty_skips_burner_query(self):
        person_id = str(uuid.uuid4())

        execute_results = [
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
        ]

        session = _make_session(execute_results, get_return=None)
        engine = FinancialIntelligenceEngine()

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            await engine.score_person(person_id, session)

        assert session.execute.call_count == 7


# ═══════════════════════════════════════════════════════════════════════════════
# Task 2a — HighInterestBorrowerScorer moderate address instability (lines 467-469)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHighInterestBorrowerScorerModerateInstability:

    def test_four_addresses_hits_moderate_branch(self):
        scorer = HighInterestBorrowerScorer()
        addresses = [MagicMock() for _ in range(4)]
        result = scorer.score([], addresses, [], None)

        assert isinstance(result, BorrowerProfile)
        assert any("moderate address instability" in s for s in result.signals)
        assert result.score <= 93

    def test_five_addresses_also_hits_moderate_branch(self):
        scorer = HighInterestBorrowerScorer()
        addresses = [MagicMock() for _ in range(5)]
        result = scorer.score([], addresses, [], None)

        assert any("moderate address instability" in s for s in result.signals)
        assert not any("high address instability" in s for s in result.signals)

    def test_six_addresses_takes_high_branch_not_moderate(self):
        scorer = HighInterestBorrowerScorer()
        addresses = [MagicMock() for _ in range(6)]
        result = scorer.score([], addresses, [], None)

        assert any("high address instability" in s for s in result.signals)
        assert not any("moderate address instability" in s for s in result.signals)

    def test_three_addresses_takes_neither_instability_branch(self):
        scorer = HighInterestBorrowerScorer()
        addresses = [MagicMock() for _ in range(3)]
        result = scorer.score([], addresses, [], None)

        assert not any("instability" in s for s in result.signals)


# ═══════════════════════════════════════════════════════════════════════════════
# Task 2b — MarketingTagsEngine.tag_person() DB orchestrator (lines 529-665)
# ═══════════════════════════════════════════════════════════════════════════════


def _marketing_person_mock(dob: date | None = None) -> MagicMock:
    m = MagicMock()
    m.date_of_birth = dob
    return m


class TestMarketingTagsEngineTagPerson:

    @pytest.mark.asyncio
    async def test_tag_person_clean_profile_returns_borrower_tag(self):
        person_id = str(uuid.uuid4())
        person_mock = _marketing_person_mock(dob=None)

        execute_results = [
            _exec_first(person_mock),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
            _exec_first(None),
        ]

        session = _make_marketing_session(execute_results)
        engine = MarketingTagsEngine()

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            results = await engine.tag_person(person_id, session)

        assert isinstance(results, list)
        borrower_tags = [t for t in results if t.tag.startswith("borrower:")]
        assert len(borrower_tags) == 1

    @pytest.mark.asyncio
    async def test_tag_person_all_10_queries_executed(self):
        person_id = str(uuid.uuid4())
        person_mock = _marketing_person_mock()

        execute_results = [
            _exec_first(person_mock),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
            _exec_first(None),
        ]

        session = _make_marketing_session(execute_results)
        engine = MarketingTagsEngine()

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            await engine.tag_person(person_id, session)

        assert session.execute.call_count == 10

    @pytest.mark.asyncio
    async def test_tag_person_with_rich_signals_produces_multiple_tags(self):
        person_id = str(uuid.uuid4())
        today = date.today()
        dob = date(today.year - 30, today.month, today.day)
        person_mock = _marketing_person_mock(dob=dob)

        crypto_wallet = MagicMock()
        crypto_wallet.mixer_exposure = False
        crypto_wallet.risk_score = 0.2
        crypto_wallet.total_volume_usd = 0.0

        social_crypto = MagicMock()
        social_crypto.handle = "defi_trader"
        social_crypto.bio = "eth blockchain nft defi"

        recent_dt = datetime.now(UTC) - timedelta(days=10)
        addr1 = MagicMock()
        addr1.country_code = "US"
        addr1.city = "Austin"
        addr1.state_province = "TX"
        addr1.updated_at = recent_dt

        addr2 = MagicMock()
        addr2.country_code = "US"
        addr2.city = "Dallas"
        addr2.state_province = "TX"
        addr2.updated_at = None

        addr3 = MagicMock()
        addr3.country_code = "US"
        addr3.city = "Houston"
        addr3.state_province = "TX"
        addr3.updated_at = None

        addr4 = MagicMock()
        addr4.country_code = "GB"
        addr4.city = "London"
        addr4.state_province = "ENG"
        addr4.updated_at = None

        wealth_mock = MagicMock()
        wealth_mock.wealth_band = "low"
        wealth_mock.vehicle_signal = 0.4
        wealth_mock.income_estimate_usd = 25_000.0
        wealth_mock.assessed_at = datetime.now(UTC)

        execute_results = [
            _exec_first(person_mock),
            _exec_all([addr1, addr2, addr3, addr4]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([crypto_wallet]),
            _exec_all([]),
            _exec_all([social_crypto]),
            _exec_first(None),
            _exec_first(wealth_mock),
        ]

        session = _make_marketing_session(execute_results)
        engine = MarketingTagsEngine()

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            results = await engine.tag_person(person_id, session)

        tags = {t.tag for t in results}
        assert any(t.startswith("borrower:") for t in tags)
        assert "crypto_investor" in tags
        assert "title_loan_candidate" in tags
        assert "recent_mover" in tags

    @pytest.mark.asyncio
    async def test_tag_person_none_person_row_no_attribute_error(self):
        person_id = str(uuid.uuid4())

        execute_results = [
            _exec_first(None),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
            _exec_first(None),
        ]

        session = _make_marketing_session(execute_results)
        engine = MarketingTagsEngine()

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            results = await engine.tag_person(person_id, session)

        assert isinstance(results, list)
        assert any(t.tag.startswith("borrower:") for t in results)

    @pytest.mark.asyncio
    async def test_tag_person_event_bus_exception_is_swallowed(self):
        person_id = str(uuid.uuid4())
        person_mock = _marketing_person_mock()

        execute_results = [
            _exec_first(person_mock),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
            _exec_first(None),
        ]

        session = _make_marketing_session(execute_results)
        engine = MarketingTagsEngine()

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=Exception("connection refused"))
            results = await engine.tag_person(person_id, session)

        assert isinstance(results, list)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_tag_person_retiring_soon_tag(self):
        person_id = str(uuid.uuid4())
        today = date.today()
        dob_63 = date(today.year - 63, today.month, today.day)
        person_mock = _marketing_person_mock(dob=dob_63)

        execute_results = [
            _exec_first(person_mock),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_all([]),
            _exec_first(None),
            _exec_first(None),
        ]

        session = _make_marketing_session(execute_results)
        engine = MarketingTagsEngine()

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=RuntimeError("no redis"))
            results = await engine.tag_person(person_id, session)

        tags = {t.tag for t in results}
        assert "retiring_soon" in tags
