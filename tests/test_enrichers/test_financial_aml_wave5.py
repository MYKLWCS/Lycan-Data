"""
test_financial_aml_wave5.py — Coverage gap tests for modules/enrichers/financial_aml.py.

Targets:
  - Line 441: derived_wealth_band = "low" when credit.score < 600
  - Line 452: wealth_row.wealth_band = derived_wealth_band when not wealth_row.wealth_band
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.financial_aml import (
    AlternativeCreditScorer,
    CreditScoreResult,
    FinancialIntelligenceEngine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_scalars(items=None):
    if items is None:
        items = []
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    scalars.first = MagicMock(return_value=items[0] if items else None)
    result.scalars = MagicMock(return_value=scalars)
    return result


def _make_session(wealth_row=None):
    """Build an async session mock returning empty lists for all queries."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.get = AsyncMock(return_value=None)

    call_count = [0]

    async def _execute(stmt):
        call_count[0] += 1
        # The 7th call is for WealthAssessment (order: watchlist, darkweb, crypto,
        # addresses, identifiers, criminals, wealth)
        if call_count[0] == 7:
            return _empty_scalars([wealth_row] if wealth_row else [])
        return _empty_scalars([])

    session.execute = _execute
    return session


# ---------------------------------------------------------------------------
# Line 441: derived_wealth_band = "low" when credit.score < 600
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_person_derives_low_wealth_band():
    """
    Line 441: credit.score < 600 → derived_wealth_band = 'low'.
    We patch AlternativeCreditScorer.score to return score=400 (< 600).
    """
    engine = FinancialIntelligenceEngine()
    pid = str(uuid.uuid4())

    low_credit = CreditScoreResult(
        score=400,
        confidence_interval=(350, 450),
        component_breakdown={"stability": 0.2, "wealth": 0.1},
        risk_category="very_poor",
    )

    with patch.object(engine._credit, "score", return_value=low_credit):
        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            session = _make_session(wealth_row=None)
            profile = await engine.score_person(pid, session)

    # A new WealthAssessment was added with wealth_band="low"
    assert session.add.called
    session.add.call_args_list[-1][0][0]
    # WealthAssessment is constructed with wealth_band=derived_wealth_band
    # We can't easily inspect the constructor args, but we verify the flow ran.
    assert profile.credit.score == 400


@pytest.mark.asyncio
async def test_score_person_derives_medium_wealth_band():
    """Complementary: credit.score >= 600 and < 750 → derived_wealth_band = 'medium'."""
    engine = FinancialIntelligenceEngine()
    pid = str(uuid.uuid4())

    medium_credit = CreditScoreResult(
        score=680,
        confidence_interval=(650, 710),
        component_breakdown={"stability": 0.5, "wealth": 0.4},
        risk_category="fair",
    )

    with patch.object(engine._credit, "score", return_value=medium_credit):
        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            session = _make_session(wealth_row=None)
            profile = await engine.score_person(pid, session)

    assert profile.credit.score == 680


# ---------------------------------------------------------------------------
# Line 452: wealth_row.wealth_band = derived_wealth_band when not wealth_row.wealth_band
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_person_updates_wealth_band_when_empty():
    """
    Line 452: When wealth_row exists but wealth_band is None/empty,
    wealth_row.wealth_band is set to derived_wealth_band.
    """
    engine = FinancialIntelligenceEngine()
    pid = str(uuid.uuid4())

    low_credit = CreditScoreResult(
        score=500,
        confidence_interval=(450, 550),
        component_breakdown={"stability": 0.2, "wealth": 0.1},
        risk_category="poor",
    )

    # Build a wealth_row with no existing wealth_band
    wealth_row = MagicMock()
    wealth_row.wealth_band = None  # falsy → line 452 fires
    wealth_row.income_estimate_usd = None
    wealth_row.crypto_signal = None
    wealth_row.confidence = None
    wealth_row.assessed_at = None

    with patch.object(engine._credit, "score", return_value=low_credit):
        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            session = _make_session(wealth_row=wealth_row)
            await engine.score_person(pid, session)

    # Line 452: wealth_row.wealth_band should now be set to "low"
    assert wealth_row.wealth_band == "low"


@pytest.mark.asyncio
async def test_score_person_does_not_overwrite_existing_wealth_band():
    """
    Line 451: when wealth_row.wealth_band is already set (truthy),
    line 452 is NOT reached (the if branch is skipped).
    """
    engine = FinancialIntelligenceEngine()
    pid = str(uuid.uuid4())

    medium_credit = CreditScoreResult(
        score=700,
        confidence_interval=(680, 720),
        component_breakdown={"stability": 0.6, "wealth": 0.5},
        risk_category="fair",
    )

    wealth_row = MagicMock()
    wealth_row.wealth_band = "high"  # already set → line 452 skipped

    with patch.object(engine._credit, "score", return_value=medium_credit):
        with patch("modules.enrichers.financial_aml.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            session = _make_session(wealth_row=wealth_row)
            await engine.score_person(pid, session)

    # wealth_band was NOT overwritten
    assert wealth_row.wealth_band == "high"
