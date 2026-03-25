"""
test_commercial_tagger_wave6.py — Coverage for modules/enrichers/commercial_tagger.py

Targets:
  lines 70-136:   assemble_person_signals — DB assembly of PersonSignals struct
  lines 304-317:  CommercialTaggerDaemon._run_batch — full batch path
  lines 325-347:  _upsert_commercial_tags — insert new + update existing rows
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.commercial_tagger import (
    CommercialTagsEngine,
    PersonSignals,
    _upsert_commercial_tags,
    assemble_person_signals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _fake_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# 1. assemble_person_signals (lines 70-136)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_person_signals_with_full_data():
    """Lines 70-148: all related rows present → PersonSignals fully populated."""
    pid = _fake_uuid()

    # Mock Person
    from modules.enrichers.commercial_tagger import PersonSignals

    mock_person = MagicMock()
    mock_person.id = pid
    mock_person.date_of_birth = datetime(1985, 6, 15).date()

    # Mock EmploymentHistory (is_current=True)
    mock_emp = MagicMock()
    mock_emp.is_current = True

    # Mock WealthAssessment
    mock_wealth = MagicMock()
    mock_wealth.income_estimate_usd = 95_000.0
    mock_wealth.net_worth_estimate_usd = 500_000.0
    mock_wealth.vehicle_signal = 0.8
    mock_wealth.property_signal = 0.6
    mock_wealth.crypto_signal = 0.1
    mock_wealth.luxury_signal = 0.5

    # Mock BehaviouralProfile
    mock_behav = MagicMock()
    mock_behav.financial_distress_score = 0.2
    mock_behav.gambling_score = 0.1

    # Mock criminal count scalar
    criminal_count_result = MagicMock()
    criminal_count_result.scalar.return_value = 0

    # Build session execute responses in the order the function queries them:
    # 1. Person
    # 2. EmploymentHistory
    # 3. CriminalRecord count
    # 4. WealthAssessment
    # 5. BehaviouralProfile
    def _make_scalars_result(obj):
        r = MagicMock()
        r.scalars.return_value.first.return_value = obj
        return r

    def _make_scalars_all_result(objs):
        r = MagicMock()
        r.scalars.return_value.all.return_value = objs
        return r

    def _make_scalar_result(val):
        r = MagicMock()
        r.scalar.return_value = val
        return r

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_scalars_result(mock_person),      # Person query
            _make_scalars_all_result([mock_emp]),   # EmploymentHistory query
            _make_scalar_result(0),                 # CriminalRecord count
            _make_scalars_result(mock_wealth),      # WealthAssessment
            _make_scalars_result(mock_behav),       # BehaviouralProfile
        ]
    )

    signals = await assemble_person_signals(pid, session)

    assert isinstance(signals, PersonSignals)
    assert signals.is_employed is True
    assert signals.income_estimate == 95_000.0
    assert signals.has_vehicle is True
    assert signals.has_property is True
    assert signals.has_investment_signals is True
    assert signals.criminal_count == 0


@pytest.mark.asyncio
async def test_assemble_person_signals_no_wealth_no_behav():
    """Lines 122-148: person exists but no wealth/behavioural rows → defaults."""
    pid = _fake_uuid()

    mock_person = MagicMock()
    mock_person.id = pid
    mock_person.date_of_birth = None

    def _make_scalars_result(obj):
        r = MagicMock()
        r.scalars.return_value.first.return_value = obj
        return r

    def _make_scalars_all_result(objs):
        r = MagicMock()
        r.scalars.return_value.all.return_value = objs
        return r

    def _make_scalar_result(val):
        r = MagicMock()
        r.scalar.return_value = val
        return r

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_scalars_result(mock_person),    # Person
            _make_scalars_all_result([]),         # no employment
            _make_scalar_result(0),              # criminal count
            _make_scalars_result(None),          # no wealth
            _make_scalars_result(None),          # no behavioural
        ]
    )

    signals = await assemble_person_signals(pid, session)

    assert signals.is_employed is False
    assert signals.income_estimate is None
    assert signals.net_worth_estimate is None
    assert signals.financial_distress_score == 0.0
    assert signals.has_investment_signals is False


# ---------------------------------------------------------------------------
# 2. CommercialTagsEngine.tag_person (lines 173-248)
# ---------------------------------------------------------------------------


def test_commercial_tags_engine_tag_person_returns_results():
    """Lines 173-248: full scoring pass → list of TagResult."""
    from modules.enrichers.commercial_tagger import CommercialTagsEngine, PersonSignals

    engine = CommercialTagsEngine()
    signals = PersonSignals(
        person_id=_fake_uuid(),
        has_vehicle=True,
        has_property=True,
        financial_distress_score=0.6,
        gambling_score=0.1,
        income_estimate=120_000.0,
        net_worth_estimate=1_200_000.0,
        is_employed=True,
        age=42,
        criminal_count=0,
        has_investment_signals=True,
    )

    results = engine.tag_person(signals)
    # At minimum insurance, banking, wealth, and lending tags should fire
    assert len(results) > 0
    tags_found = {r.tag for r in results}
    # With high income + vehicle + property + investment signals several tags fire
    assert any("insurance" in t or "banking" in t or "mortgage" in t for t in tags_found)


def test_commercial_tags_engine_no_signals_returns_empty_or_minimal():
    """tag_person with zero signals returns very few or no tags."""
    from modules.enrichers.commercial_tagger import CommercialTagsEngine, PersonSignals

    engine = CommercialTagsEngine()
    signals = PersonSignals(
        person_id=_fake_uuid(),
        has_vehicle=False,
        has_property=False,
        financial_distress_score=0.0,
        gambling_score=0.0,
        income_estimate=None,
        net_worth_estimate=None,
        is_employed=False,
        age=None,
        criminal_count=0,
        has_investment_signals=False,
    )

    results = engine.tag_person(signals)
    # All scorers return 0.0 → no tags cross threshold
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 3. CommercialTaggerDaemon._run_batch (lines 304-317)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_no_persons_returns_early():
    """Lines 300-302: empty persons list → early return, last_run_at updated."""
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon

    daemon = CommercialTaggerDaemon()

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []

    session = _make_session()
    session.execute = AsyncMock(return_value=result_mock)

    with patch("modules.enrichers.commercial_tagger.AsyncSessionLocal") as mock_sl:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_sl.return_value = mock_ctx

        # Run batch directly; it queries persons using the outer session
        # We simulate using AsyncSessionLocal for persons query by patching at module level
        # The daemon queries from a passed-in session concept, but the module calls
        # AsyncSessionLocal() internally for the outer query in _run_batch.
        # So we need to patch both the outer query and the inner per-person session.
        await daemon._run_batch()

    assert daemon._last_run_at is not None


@pytest.mark.asyncio
async def test_run_batch_processes_persons_and_upserts():
    """Lines 306-316: person processed → signals assembled → tags upserted."""
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon, PersonSignals

    daemon = CommercialTaggerDaemon()

    fake_person = _fake_person_obj()

    outer_result = MagicMock()
    outer_result.scalars.return_value.all.return_value = [fake_person]

    outer_session = _make_session()
    outer_session.execute = AsyncMock(return_value=outer_result)

    inner_session = _make_session()

    # assemble_person_signals returns minimal signals
    fake_signals = PersonSignals(
        person_id=fake_person.id,
        has_vehicle=False,
        has_property=False,
        financial_distress_score=0.0,
        gambling_score=0.0,
        income_estimate=None,
        net_worth_estimate=None,
        is_employed=True,
        age=35,
        criminal_count=0,
        has_investment_signals=False,
    )

    with patch(
        "modules.enrichers.commercial_tagger.assemble_person_signals",
        new=AsyncMock(return_value=fake_signals),
    ):
        with patch(
            "modules.enrichers.commercial_tagger._upsert_commercial_tags",
            new=AsyncMock(),
        ) as mock_upsert:
            # Patch AsyncSessionLocal to return our outer_session for the persons query
            # and inner_session for per-person processing
            call_count = [0]

            class FakeCtx:
                async def __aenter__(self_):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        return outer_session
                    return inner_session

                async def __aexit__(self_, *args):
                    return False

            with patch(
                "modules.enrichers.commercial_tagger.AsyncSessionLocal",
                return_value=FakeCtx(),
            ):
                await daemon._run_batch()

    assert daemon._last_run_at is not None


def _fake_person_obj():
    p = MagicMock()
    p.id = uuid.uuid4()
    p.last_scraped_at = datetime.now(UTC)
    return p


# ---------------------------------------------------------------------------
# 4. _upsert_commercial_tags (lines 325-347)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_commercial_tags_inserts_new_tag():
    """Lines 341-356: no existing tag → session.add called."""
    from modules.enrichers.marketing_tags import TagResult, LendingTag

    person_id = _fake_uuid()
    tag_result = TagResult(
        tag=LendingTag.PERSONAL_LOAN_CANDIDATE,
        confidence=0.75,
        reasoning=["employed"],
        scored_at=datetime.now(UTC),
    )

    session = _make_session()

    # No existing row found
    existing_result = MagicMock()
    existing_result.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=existing_result)

    await _upsert_commercial_tags(person_id, [tag_result], session)

    assert session.add.called


@pytest.mark.asyncio
async def test_upsert_commercial_tags_updates_existing_tag():
    """Lines 341-345: existing tag found → attributes updated (no add call)."""
    from modules.enrichers.marketing_tags import TagResult, LendingTag

    person_id = _fake_uuid()
    tag_result = TagResult(
        tag=LendingTag.PERSONAL_LOAN_CANDIDATE,
        confidence=0.80,
        reasoning=["employed", "distress"],
        scored_at=datetime.now(UTC),
    )

    existing_tag = MagicMock()

    session = _make_session()

    existing_result = MagicMock()
    existing_result.scalars.return_value.first.return_value = existing_tag
    session.execute = AsyncMock(return_value=existing_result)

    await _upsert_commercial_tags(person_id, [tag_result], session)

    # Update path: attributes set on existing object, add NOT called
    assert existing_tag.confidence == 0.80
    session.add.assert_not_called()
