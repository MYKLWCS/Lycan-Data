"""
Tests for modules/pipeline/enrichment_orchestrator.py

Covers:
- enrich_person returns a fully-populated EnrichmentReport
- Each step status is captured (ok, error)
- A failing enricher does not abort subsequent steps
- ok_count / error_count properties work correctly
- _publish_completion is a no-op when event_bus is not connected
- _publish_completion is called when bus is connected
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.pipeline.enrichment_orchestrator import (
    EnrichmentOrchestrator,
    EnrichmentReport,
    EnrichmentStepResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


async def _noop(*args, **kwargs) -> None:  # noqa: D401
    return None


# ---------------------------------------------------------------------------
# 1. enrich_person returns EnrichmentReport with all five steps
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enrich_person_returns_report_with_five_steps():
    orchestrator = EnrichmentOrchestrator()
    session = _mock_session()

    # Patch all nine private step methods to be no-ops
    with (
        patch.object(orchestrator, "_run_financial_aml", new=AsyncMock()),
        patch.object(orchestrator, "_run_marketing_tags", new=AsyncMock()),
        patch.object(orchestrator, "_run_deduplication", new=AsyncMock()),
        patch.object(orchestrator, "_run_burner", new=AsyncMock()),
        patch.object(orchestrator, "_run_relationship_score", new=AsyncMock()),
        patch.object(orchestrator, "_update_coverage", new=AsyncMock()),
        patch.object(orchestrator, "_run_location", new=AsyncMock()),
        patch.object(orchestrator, "_run_cascade", new=AsyncMock()),
        patch.object(orchestrator, "_run_entity_resolution", new=AsyncMock()),
        patch.object(orchestrator, "_compute_enrichment_score", new=AsyncMock()),
        patch.object(orchestrator, "_publish_completion", new=AsyncMock()),
    ):
        report = await orchestrator.enrich_person("person-123", session)

    assert isinstance(report, EnrichmentReport)
    assert report.person_id == "person-123"
    assert len(report.steps) == 10
    enricher_names = [s.enricher for s in report.steps]
    assert "financial_aml" in enricher_names
    assert "marketing_tags" in enricher_names
    assert "deduplication" in enricher_names
    assert "burner_assessment" in enricher_names
    assert "relationship_score" in enricher_names
    assert "coverage_update" in enricher_names
    assert "location" in enricher_names
    assert "cascade" in enricher_names


# ---------------------------------------------------------------------------
# 2. All steps succeed → ok_count == 5, error_count == 0
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enrich_person_all_ok():
    orchestrator = EnrichmentOrchestrator()
    session = _mock_session()

    with (
        patch.object(orchestrator, "_run_financial_aml", new=AsyncMock()),
        patch.object(orchestrator, "_run_marketing_tags", new=AsyncMock()),
        patch.object(orchestrator, "_run_deduplication", new=AsyncMock()),
        patch.object(orchestrator, "_run_burner", new=AsyncMock()),
        patch.object(orchestrator, "_run_relationship_score", new=AsyncMock()),
        patch.object(orchestrator, "_update_coverage", new=AsyncMock()),
        patch.object(orchestrator, "_run_location", new=AsyncMock()),
        patch.object(orchestrator, "_run_cascade", new=AsyncMock()),
        patch.object(orchestrator, "_run_entity_resolution", new=AsyncMock()),
        patch.object(orchestrator, "_compute_enrichment_score", new=AsyncMock()),
        patch.object(orchestrator, "_publish_completion", new=AsyncMock()),
    ):
        report = await orchestrator.enrich_person("abc", session)

    assert report.ok_count == 10
    assert report.error_count == 0


# ---------------------------------------------------------------------------
# 3. One failing enricher does not abort subsequent steps
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failing_enricher_does_not_abort_pipeline():
    orchestrator = EnrichmentOrchestrator()
    session = _mock_session()

    async def _boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    with (
        patch.object(orchestrator, "_run_financial_aml", new=AsyncMock(side_effect=_boom)),
        patch.object(orchestrator, "_run_marketing_tags", new=AsyncMock()),
        patch.object(orchestrator, "_run_deduplication", new=AsyncMock()),
        patch.object(orchestrator, "_run_burner", new=AsyncMock()),
        patch.object(orchestrator, "_run_relationship_score", new=AsyncMock()),
        patch.object(orchestrator, "_update_coverage", new=AsyncMock()),
        patch.object(orchestrator, "_run_location", new=AsyncMock()),
        patch.object(orchestrator, "_run_cascade", new=AsyncMock()),
        patch.object(orchestrator, "_run_entity_resolution", new=AsyncMock()),
        patch.object(orchestrator, "_compute_enrichment_score", new=AsyncMock()),
        patch.object(orchestrator, "_publish_completion", new=AsyncMock()),
    ):
        report = await orchestrator.enrich_person("xyz", session)

    assert len(report.steps) == 10
    assert report.error_count == 1
    assert report.ok_count == 9
    failed_step = next(s for s in report.steps if s.enricher == "financial_aml")
    assert failed_step.status == "error"
    assert "injected failure" in failed_step.detail


# ---------------------------------------------------------------------------
# 4. _run_step captures detail string up to 200 chars on error
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_step_truncates_detail_at_200_chars():
    orchestrator = EnrichmentOrchestrator()
    long_message = "x" * 500

    async def _boom():
        raise ValueError(long_message)

    result = await orchestrator._run_step("test_enricher", _boom())
    assert result.status == "error"
    assert len(result.detail) == 200


# ---------------------------------------------------------------------------
# 5. _publish_completion is a no-op when event_bus is disconnected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_completion_skipped_when_not_connected():
    orchestrator = EnrichmentOrchestrator()
    report = EnrichmentReport(
        person_id="p1",
        started_at="2024-01-01T00:00:00+00:00",
        finished_at="2024-01-01T00:00:01+00:00",
        total_duration_ms=1000.0,
        steps=[],
    )

    with patch("modules.pipeline.enrichment_orchestrator.event_bus") as mock_bus:
        mock_bus.is_connected = False
        mock_bus.publish = AsyncMock()
        await orchestrator._publish_completion("p1", report)
        mock_bus.publish.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. _publish_completion calls event_bus.publish when connected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_completion_calls_publish_when_connected():
    orchestrator = EnrichmentOrchestrator()
    report = EnrichmentReport(
        person_id="p2",
        started_at="2024-01-01T00:00:00+00:00",
        finished_at="2024-01-01T00:00:01+00:00",
        total_duration_ms=500.0,
        steps=[
            EnrichmentStepResult(enricher="financial_aml", status="ok"),
            EnrichmentStepResult(enricher="marketing_tags", status="error", detail="oops"),
        ],
    )

    with patch("modules.pipeline.enrichment_orchestrator.event_bus") as mock_bus:
        mock_bus.is_connected = True
        mock_bus.publish = AsyncMock()
        await orchestrator._publish_completion("p2", report)

    mock_bus.publish.assert_awaited_once()
    call_args = mock_bus.publish.call_args
    channel = call_args.args[0]
    payload = call_args.args[1]
    assert channel == "enrichment"
    assert payload["event"] == "enrichment_complete"
    assert payload["person_id"] == "p2"
    assert payload["ok_count"] == 1
    assert payload["error_count"] == 1
