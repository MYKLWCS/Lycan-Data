"""
test_orchestrator_wave6.py — Coverage for _update_coverage (lines 267-316)
in modules/pipeline/enrichment_orchestrator.py.

Targets:
  267-316: _update_coverage
    - person not found → early return
    - person found → queries attempted/found/total_enabled → meta updated
    - flush/commit raises → rollback called
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(person=None, attempted=3, found=2, total_enabled=10):
    """Build a mock session whose .get() returns `person` and whose
    .execute() returns scalar counts in the correct order."""
    session = AsyncMock()

    session.get = AsyncMock(return_value=person)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    def _make_scalar(val):
        r = MagicMock()
        r.scalar.return_value = val
        return r

    session.execute = AsyncMock(
        side_effect=[
            _make_scalar(attempted),  # attempted CrawlJob count
            _make_scalar(found),  # found CrawlJob count
            _make_scalar(total_enabled),  # enabled DataSources count
        ]
    )

    return session


def _fake_person():
    p = MagicMock()
    p.meta = {}
    p.relationship_score = 0.0
    return p


# ---------------------------------------------------------------------------
# 1. person not found → early return (line 267-268)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_coverage_person_not_found_returns_early():
    """Lines 266-268: session.get returns None → immediate return, no DB writes."""
    orchestrator = EnrichmentOrchestrator()
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    await orchestrator._update_coverage(str(uuid.uuid4()), session)

    # Should not have attempted any further queries
    session.execute.assert_not_called()
    session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# 2. person found → queries run → meta.coverage updated → flush + commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_coverage_computes_and_stores_coverage():
    """Lines 270-313: full path — meta['coverage'] set and flushed."""
    orchestrator = EnrichmentOrchestrator()
    person = _fake_person()
    session = _make_session(person=person, attempted=5, found=3, total_enabled=10)

    await orchestrator._update_coverage(str(uuid.uuid4()), session)

    assert "coverage" in person.meta
    cov = person.meta["coverage"]
    assert cov["attempted"] == 5
    assert cov["found"] == 3
    assert cov["total_enabled"] == 10
    assert cov["pct"] == round(min(100.0, 3 / 10 * 100), 1)

    session.flush.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_coverage_pct_clamped_to_100():
    """Line 300: pct is clamped to 100.0 when found > total_enabled."""
    orchestrator = EnrichmentOrchestrator()
    person = _fake_person()
    # found (15) > total_enabled (10) → pct would be 150 → clamped to 100
    session = _make_session(person=person, attempted=15, found=15, total_enabled=10)

    await orchestrator._update_coverage(str(uuid.uuid4()), session)

    assert person.meta["coverage"]["pct"] == 100.0


@pytest.mark.asyncio
async def test_update_coverage_zero_enabled_uses_denominator_1():
    """Line 298: total_enabled=0 → or 1 guard prevents ZeroDivisionError."""
    orchestrator = EnrichmentOrchestrator()
    person = _fake_person()
    session = _make_session(person=person, attempted=0, found=0, total_enabled=0)

    # Should not raise ZeroDivisionError
    await orchestrator._update_coverage(str(uuid.uuid4()), session)

    assert person.meta["coverage"]["pct"] == 0.0


# ---------------------------------------------------------------------------
# 3. flush/commit raises → rollback called (lines 314-316)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_coverage_flush_raises_triggers_rollback():
    """Lines 311-316: flush raises → warning logged, rollback called."""
    orchestrator = EnrichmentOrchestrator()
    person = _fake_person()

    session = AsyncMock()
    session.get = AsyncMock(return_value=person)

    def _make_scalar(val):
        r = MagicMock()
        r.scalar.return_value = val
        return r

    session.execute = AsyncMock(
        side_effect=[
            _make_scalar(2),
            _make_scalar(1),
            _make_scalar(5),
        ]
    )
    session.flush = AsyncMock(side_effect=RuntimeError("flush failed"))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    await orchestrator._update_coverage(str(uuid.uuid4()), session)

    session.rollback.assert_called_once()
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Existing meta is preserved (merged with new coverage key)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_coverage_preserves_existing_meta():
    """Line 302: existing meta keys are preserved when coverage is updated."""
    orchestrator = EnrichmentOrchestrator()
    person = _fake_person()
    person.meta = {"some_key": "some_value"}

    session = _make_session(person=person, attempted=1, found=1, total_enabled=5)

    await orchestrator._update_coverage(str(uuid.uuid4()), session)

    assert person.meta["some_key"] == "some_value"
    assert "coverage" in person.meta


# ---------------------------------------------------------------------------
# 5. Full enrich_person pipeline calls _update_coverage as step 6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_person_includes_coverage_update_step():
    """Verify _update_coverage is wired into enrich_person as step 6."""
    orchestrator = EnrichmentOrchestrator()
    session = AsyncMock()

    with (
        patch.object(orchestrator, "_run_financial_aml", new=AsyncMock()),
        patch.object(orchestrator, "_run_marketing_tags", new=AsyncMock()),
        patch.object(orchestrator, "_run_deduplication", new=AsyncMock()),
        patch.object(orchestrator, "_run_burner", new=AsyncMock()),
        patch.object(orchestrator, "_run_relationship_score", new=AsyncMock()),
        patch.object(orchestrator, "_update_coverage", new=AsyncMock()) as mock_cov,
        patch.object(orchestrator, "_run_location", new=AsyncMock()),
        patch.object(orchestrator, "_run_cascade", new=AsyncMock()),
        patch.object(orchestrator, "_run_entity_resolution", new=AsyncMock()),
        patch.object(orchestrator, "_compute_enrichment_score", new=AsyncMock()),
        patch.object(orchestrator, "_publish_completion", new=AsyncMock()),
    ):
        report = await orchestrator.enrich_person(str(uuid.uuid4()), session)

    assert mock_cov.called
    assert len(report.steps) == 10
    step_names = [s.enricher for s in report.steps]
    assert "coverage_update" in step_names
