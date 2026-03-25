"""Tests for AutoDedupDaemon — background deduplication daemon."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# Import all models upfront so SQLAlchemy can resolve string-based relationships
import shared.models.criminal  # noqa: F401
import shared.models.identifier  # noqa: F401
import shared.models.social_profile  # noqa: F401
import shared.models.address  # noqa: F401
import shared.models.identifier_history  # noqa: F401
import shared.models.identity_document  # noqa: F401
from modules.enrichers.auto_dedup import AutoDedupDaemon
from modules.enrichers.deduplication import MergeCandidate


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_person(pid=None, fields=5):
    """Return a mock Person ORM object."""
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.merged_into = None
    p._field_count = fields  # used by mock _count_populated_fields
    return p


def _candidate(id_a, id_b, score):
    return MergeCandidate(
        id_a=str(id_a), id_b=str(id_b),
        similarity_score=score, match_reasons=["name_match"]
    )


# ── Unit tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daemon_instantiates():
    daemon = AutoDedupDaemon()
    assert daemon is not None


@pytest.mark.asyncio
async def test_run_batch_auto_merges_high_score(monkeypatch):
    """Score >= 0.85 triggers immediate merge."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    # Mock recent persons query
    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [
        _make_person(pid=person_a_id)
    ]

    # Mock score_person_dedup returning high-score candidate
    candidate = _candidate(person_a_id, person_b_id, 0.92)

    # Mock _count_populated_fields: person_a has more fields → canonical
    async def mock_count(person, sess):
        return 20 if person.id == person_a_id else 10

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[candidate])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = mock_count
        session.execute = AsyncMock(return_value=mock_persons_result)

        mock_exec_instance = AsyncMock()
        mock_exec_instance.execute = AsyncMock(return_value={"merged": True})
        MockExec.return_value = mock_exec_instance

        await daemon._run_batch(session)

        assert MockExec.called, "AsyncMergeExecutor should have been called for score 0.92"


@pytest.mark.asyncio
async def test_run_batch_queues_medium_score(monkeypatch):
    """Score 0.70-0.84 inserts DedupReview row, does NOT merge."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [
        _make_person(pid=person_a_id)
    ]

    candidate = _candidate(person_a_id, person_b_id, 0.77)

    added_objects = []
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[candidate])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = AsyncMock(return_value=5)
        session.execute = AsyncMock(return_value=mock_persons_result)

        await daemon._run_batch(session)

        MockExec.assert_not_called()
        assert any(
            hasattr(obj, "similarity_score") and obj.similarity_score == 0.77
            for obj in added_objects
        ), "DedupReview row should have been added to session"


@pytest.mark.asyncio
async def test_run_batch_skips_low_score(monkeypatch):
    """Score < 0.70 is silently skipped — no merge, no review row."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [
        _make_person(pid=person_a_id)
    ]

    candidate = _candidate(person_a_id, person_b_id, 0.45)

    added_objects = []
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[candidate])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = AsyncMock(return_value=5)
        session.execute = AsyncMock(return_value=mock_persons_result)

        await daemon._run_batch(session)

        MockExec.assert_not_called()
        assert len(added_objects) == 0, "Nothing should be added for low score"
