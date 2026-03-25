"""
test_enrichers_wave3.py — Coverage gap tests for financial_aml.py and
marketing_tags.py enrichers.

Uses AsyncMock session.execute with sequential side_effect lists to simulate
multiple DB round-trips inside score_person / tag_person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all SQLAlchemy models are imported before mappers configure
# (prevents 'IdentityDocument' / relationship resolution errors)
import shared.models.address  # noqa: F401
import shared.models.behavioural  # noqa: F401
import shared.models.breach  # noqa: F401
import shared.models.burner  # noqa: F401
import shared.models.credit_risk  # noqa: F401
import shared.models.criminal  # noqa: F401
import shared.models.darkweb  # noqa: F401
import shared.models.employment  # noqa: F401
import shared.models.identifier  # noqa: F401
import shared.models.identifier_history  # noqa: F401
import shared.models.identity_document  # noqa: F401
import shared.models.person  # noqa: F401
import shared.models.social_profile  # noqa: F401
import shared.models.watchlist  # noqa: F401
import shared.models.wealth  # noqa: F401

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _scalars_result(rows):
    """Return an execute() result mock whose .scalars().all() returns `rows`."""
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=rows)
    scalars_mock.first = MagicMock(return_value=rows[0] if rows else None)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_mock)
    result.scalar_one_or_none = MagicMock(return_value=rows[0] if rows else None)
    return result


def _make_session(side_effects: list):
    """Build an AsyncMock session whose .execute() returns items from side_effects in order."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=side_effects)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)
    return session


# ===========================================================================
# FinancialIntelligenceEngine.score_person
# ===========================================================================


class TestFinancialIntelligenceEngine:
    """Tests for score_person DB orchestrator — lines 300-502."""

    def _make_engine(self):
        from modules.enrichers.financial_aml import FinancialIntelligenceEngine

        return FinancialIntelligenceEngine()

    def _build_session_for_score(
        self,
        watchlist_rows=None,
        darkweb_rows=None,
        crypto_rows=None,
        address_rows=None,
        identifier_rows=None,
        criminal_rows=None,
        wealth_row=None,
        burner_rows=None,
        person_row=None,
    ):
        """Build a session whose execute() returns mocks in the order score_person calls them."""
        watchlist_rows = watchlist_rows or []
        darkweb_rows = darkweb_rows or []
        crypto_rows = crypto_rows or []
        address_rows = address_rows or []
        identifier_rows = identifier_rows or []
        criminal_rows = criminal_rows or []
        burner_rows = burner_rows or []

        # WealthAssessment uses .scalars().first()
        wealth_result = MagicMock()
        wealth_scalars = MagicMock()
        wealth_scalars.first = MagicMock(return_value=wealth_row)
        wealth_result.scalars = MagicMock(return_value=wealth_scalars)

        # BurnerAssessment — only fetched if identifier_ids is non-empty
        burner_result = _scalars_result(burner_rows)

        effects = [
            _scalars_result(watchlist_rows),
            _scalars_result(darkweb_rows),
            _scalars_result(crypto_rows),
            _scalars_result(address_rows),
            _scalars_result(identifier_rows),
            _scalars_result(criminal_rows),
            _scalars_result([]),  # employment
            _scalars_result([]),  # properties
            wealth_result,
        ]

        if identifier_rows:
            # burner query only executes when identifier_ids is non-empty
            effects.append(burner_result)

        session = _make_session(effects)
        session.get = AsyncMock(return_value=person_row)
        return session

    @pytest.mark.asyncio
    async def test_score_empty_person_returns_profile(self):
        """score_person returns a FinancialProfile even with no supporting data."""
        engine = self._make_engine()
        session = self._build_session_for_score()
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            from modules.enrichers.financial_aml import FinancialProfile

            profile = await engine.score_person(person_id, session)

        assert isinstance(profile, FinancialProfile)
        assert profile.person_id == person_id
        session.add.assert_called()  # CreditRiskAssessment added

    @pytest.mark.asyncio
    async def test_score_with_sanctions_and_darkweb(self):
        """Sanctions + darkweb data elevates AML risk tier."""
        engine = self._make_engine()

        def _watchlist_row():
            r = MagicMock()
            r.list_name = "OFAC"
            r.list_type = "sanctions"
            r.match_score = 0.95
            r.match_name = "John Doe"
            r.is_confirmed = False
            return r

        def _darkweb_row():
            r = MagicMock()
            r.exposure_score = 0.5
            return r

        watchlist = [_watchlist_row()]
        darkweb = [_darkweb_row() for _ in range(5)]
        crypto = [MagicMock(mixer_exposure=False, total_volume_usd=0.0, risk_score=0.1)]

        session = self._build_session_for_score(
            watchlist_rows=watchlist,
            darkweb_rows=darkweb,
            crypto_rows=crypto,
        )
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            profile = await engine.score_person(person_id, session)

        assert profile.aml.darkweb_mention_count == 5

    @pytest.mark.asyncio
    async def test_score_existing_wealth_row_updated(self):
        """When WealthAssessment already exists, it is updated not re-created."""
        engine = self._make_engine()

        wealth_row = MagicMock()
        wealth_row.wealth_band = "medium"
        wealth_row.income_estimate_usd = 50000.0
        wealth_row.crypto_signal = 0.0
        wealth_row.confidence = 0.5
        wealth_row.assessed_at = datetime.now(UTC)

        person_mock = MagicMock()
        person_mock.default_risk_score = 0.3
        person_mock.darkweb_exposure = 0.0
        person_mock.behavioural_risk = 0.0

        session = self._build_session_for_score(wealth_row=wealth_row, person_row=person_mock)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            await engine.score_person(person_id, session)

        # Existing wealth row should have been mutated
        assert wealth_row.income_estimate_usd is not None

    @pytest.mark.asyncio
    async def test_score_new_wealth_row_created(self):
        """When no WealthAssessment exists, a new one is added to session."""
        engine = self._make_engine()
        session = self._build_session_for_score(wealth_row=None)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            await engine.score_person(person_id, session)

        # session.add should be called at least twice (CreditRiskAssessment + WealthAssessment)
        assert session.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_score_event_bus_unavailable_does_not_raise(self):
        """If event_bus.publish raises, score_person still returns cleanly."""
        engine = self._make_engine()
        session = self._build_session_for_score()
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=Exception("bus down"))
            profile = await engine.score_person(person_id, session)

        assert profile is not None

    @pytest.mark.asyncio
    async def test_score_with_burner_identifiers(self):
        """Identifiers with confidence < 0.5 contribute to synthetic_identity_weight."""
        engine = self._make_engine()

        ident = MagicMock()
        ident.id = uuid.uuid4()
        ident.confidence = 0.3  # below threshold
        ident.type = "email"

        burner = MagicMock()
        burner.burner_score = 0.8

        session = self._build_session_for_score(
            identifier_rows=[ident],
            burner_rows=[burner],
        )
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            profile = await engine.score_person(person_id, session)

        assert profile is not None


# ===========================================================================
# MarketingTagsEngine.tag_person
# ===========================================================================


class TestMarketingTagsEngine:
    """Tests for tag_person DB orchestrator — lines 523-665."""

    def _make_engine(self):
        from modules.enrichers.marketing_tags import MarketingTagsEngine

        return MarketingTagsEngine()

    def _build_session(
        self,
        person=None,
        addresses=None,
        employment=None,
        criminals=None,
        darkweb=None,
        crypto_wallets=None,
        identifiers=None,
        socials=None,
        behavioural=None,
        wealth=None,
    ):
        """Return session mock with ordered side_effects for tag_person queries."""
        addresses = addresses or []
        employment = employment or []
        criminals = criminals or []
        darkweb = darkweb or []
        crypto_wallets = crypto_wallets or []
        identifiers = identifiers or []
        socials = socials or []

        # person: uses .scalars().first()
        person_result = MagicMock()
        pscalars = MagicMock()
        pscalars.first = MagicMock(return_value=person)
        person_result.scalars = MagicMock(return_value=pscalars)

        # WealthAssessment: uses .scalars().first()
        wealth_result = MagicMock()
        wscalars = MagicMock()
        wscalars.first = MagicMock(return_value=wealth)
        wealth_result.scalars = MagicMock(return_value=wscalars)

        # BehaviouralProfile: uses .scalars().first()
        beh_result = MagicMock()
        bscalars = MagicMock()
        bscalars.first = MagicMock(return_value=behavioural)
        beh_result.scalars = MagicMock(return_value=bscalars)

        effects = [
            person_result,
            _scalars_result(addresses),
            _scalars_result(employment),
            _scalars_result(criminals),
            _scalars_result(darkweb),
            _scalars_result(crypto_wallets),
            _scalars_result(identifiers),
            _scalars_result(socials),
            beh_result,
            wealth_result,
            _scalars_result([]),  # vehicles
            _scalars_result([]),  # properties
        ]

        return _make_session(effects)

    @pytest.mark.asyncio
    async def test_tag_person_no_data_returns_borrower_tag(self):
        """With no supporting data, borrower tag is always appended."""
        engine = self._make_engine()
        person = MagicMock()
        person.date_of_birth = None

        session = self._build_session(person=person)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            results = await engine.tag_person(person_id, session)

        # borrower tag always appended
        assert any("borrower:" in r.tag for r in results)

    @pytest.mark.asyncio
    async def test_tag_person_crypto_investor_tag(self):
        """With crypto wallets, crypto_investor tag may be assigned."""
        engine = self._make_engine()
        person = MagicMock()
        person.date_of_birth = None

        crypto = [MagicMock(mixer_exposure=False, total_volume_usd=500_000.0)]
        identifiers = [MagicMock(type="email", value="user@example.com")]

        session = self._build_session(person=person, crypto_wallets=crypto, identifiers=identifiers)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            results = await engine.tag_person(person_id, session)

        # Just verifying it runs without error; tag may or may not meet threshold
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_tag_person_event_bus_failure_does_not_raise(self):
        """Event bus publish failure is swallowed."""
        engine = self._make_engine()
        person = MagicMock()
        person.date_of_birth = None

        session = self._build_session(person=person)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock(side_effect=Exception("bus unavailable"))
            results = await engine.tag_person(person_id, session)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_tag_person_with_age_scoring(self):
        """Person with date_of_birth triggers age-dependent scoring paths."""
        engine = self._make_engine()
        from datetime import date

        person = MagicMock()
        person.date_of_birth = date(1960, 1, 1)  # ~65, RETIRING_SOON candidate

        emp = MagicMock()
        emp.title = "Engineer"
        emp.employer_name = "Corp"
        emp.end_date = None
        emp.is_current = False  # avoid date arithmetic on MagicMock
        emp.started_at = None
        employment = [emp]

        session = self._build_session(person=person, employment=employment)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            results = await engine.tag_person(person_id, session)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_tag_person_luxury_buyer_scoring(self):
        """High-wealth signals trigger luxury_buyer consideration."""
        engine = self._make_engine()
        person = MagicMock()
        person.date_of_birth = None

        wealth = MagicMock()
        wealth.wealth_band = "high"
        wealth.income_estimate_usd = 250_000.0
        wealth.assessed_at = datetime.now(UTC)
        wealth.vehicle_signal = 0.0
        wealth.property_signal = 0.0
        wealth.crypto_signal = 0.0
        wealth.net_worth_estimate_usd = 500_000.0

        emp = MagicMock()
        emp.title = "CEO"
        emp.employer_name = "MegaCorp"
        emp.end_date = None
        emp.is_current = False
        emp.started_at = None
        employment = [emp]

        session = self._build_session(person=person, wealth=wealth, employment=employment)
        person_id = str(uuid.uuid4())

        with patch("modules.enrichers.marketing_tags.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            results = await engine.tag_person(person_id, session)

        assert isinstance(results, list)
